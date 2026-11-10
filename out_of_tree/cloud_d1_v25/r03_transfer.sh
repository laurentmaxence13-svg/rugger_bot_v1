#!/bin/bash
# W1 D1 — RUGGER 03 side of the transfer. Each mode needs the owner's GO (network to storage.googleapis.com,
# wheel download, signed URLs). Signed URLs are SECRETS: they are read from a file, passed to curl through its
# config on stdin (never on the command line, never printed); only names, HTTP codes and sha256 are logged.
#   prepare  DAYJ_DIR W1AUX_PKG CODE_REPO CODE_REF P0_REGISTRY CLOUD_PKG OUT_DIR   (offline except `pip download`)
#   put      BUCKET OUT_DIR      RECOMMENDED: no secret here; the proxy injects the owner's CAB token (inbound/ only)
#   get      BUCKET DEST_DIR     RECOMMENDED: same, with the outbound/ token (fixed object names: a CAB token cannot list)
#   upload   inbound_put_urls.tsv OUT_DIR     fallback with signed URLs
#   download outbound_get_urls.tsv DEST_DIR   fallback with signed URLs
set -euo pipefail
die() { echo "STOP: $*"; exit 2; }
sha() { sha256sum "$1" | cut -d' ' -f1; }

case "${1:-}" in
prepare)
  [ $# = 8 ] || die "usage: prepare DAYJ_DIR W1AUX_PKG CODE_REPO CODE_REF P0_REGISTRY CLOUD_PKG OUT_DIR"
  dayj=$2; pkg=$3; repo=$4; ref=$5;   # ref NAME (e.g. refs/r03-audit/...): a bundle needs a ref
  reg=$6; cloud=$7; out=$8
  [ ! -e "$out" ] || die "out_exists"; mkdir -p "$out/wheels"
  git -C "$repo" show-ref --verify --quiet "$ref" || die "not_a_ref:$ref"
  [ "$(git -C "$repo" rev-parse "$ref^{tree}")" = aff97638cd011bcc3dc2b2826d42a208eb855aed ] || die frozen_tree
  commit=$(git -C "$repo" rev-parse "$ref^{commit}")
  [ "$(sha "$reg")" = f1f26e366bec2cdc3093bf027617d453d6d7dfbdd4b721173c290433004f47de ] || die p0_registry
  m=$(cd "$pkg" && find w1aux -type f ! -path '*__pycache__*' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1)
  [ "$m" = 63eb3412a94483002a0a43833e73dad79e536be03254e5507c5464de0041c420 ] || die "w1aux_manifest:$m"
  git -C "$repo" bundle create "$out/w1code.bundle" "$ref"
  tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner --exclude='__pycache__' -cf "$out/w1aux_v73.tar" -C "$pkg" w1aux
  # the dayj directory without resume data and without any pickle (R02 C4)
  tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner --exclude=./checkpoint --exclude='*.pkl' \
      -cf "$out/dayj_out.tar" -C "$dayj" .
  tar -tf "$out/dayj_out.tar" > "$out.list"; if grep -qE '\.pkl$' "$out.list"; then die pickle_in_dayj_out; fi; rm "$out.list"
  # R02 (d): no secret may leave in dayj_out.tar (export/collection manifests may keep an endpoint); values never printed
  python3 -I - "$out/dayj_out.tar" <<'EOF' || die secret_pattern_in_dayj_out
import gzip, re, sys, tarfile
pat = re.compile(rb'api[-_]?key=|[?&]key=|apikey|x-api-key"?\s*[:=]\s*"?[A-Za-z0-9]|helius-rpc\.com/\?|BEGIN [A-Z ]*PRIVATE', re.I)
hits = []
with tarfile.open(sys.argv[1]) as tar:
    for m in tar:
        if m.name.rstrip('/').endswith('.env') or '/.env' in m.name:
            hits.append(m.name); continue
        if not m.isfile():
            continue
        data = tar.extractfile(m).read()
        if m.name.endswith('.gz'):
            try:
                data = gzip.decompress(data)
            except (OSError, EOFError):
                pass                                   # not gzip after all: scan the raw bytes
        if pat.search(data):
            hits.append(m.name)
for h in hits:
    print('secret-like pattern in', h)          # the member name only, never the value
sys.exit(1 if hits else 0)
EOF
  cp "$reg" "$out/p0_trials.jsonl"; cp "$cloud/identity_check.py" "$cloud/IDENTITY_REFERENCE.json" "$out/"
  # pinned wheels (GO required: PyPI download), cp312 manylinux x86_64 or pure python, no dependency resolution
  python3 -m pip download --only-binary=:all: --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 \
      --python-version 3.12 --implementation cp --abi cp312 --no-deps -r "$cloud/requirements-dayj.txt" -d "$out/wheels"
  [ "$(ls "$out/wheels" | wc -l)" = "$(grep -cE '^[a-zA-Z]' "$cloud/requirements-dayj.txt")" ] || die wheel_count
  # R02 (e)/O-7: each wheel's sha256 must equal the digest PyPI publishes for that exact file (JSON API, same GO)
  python3 -I - "$out/wheels" "$cloud/requirements-dayj.txt" > "$out.pypi_digests.txt" <<'EOF' || die wheel_not_pypi_digest
import hashlib, json, pathlib, sys, urllib.request
wheels, req = pathlib.Path(sys.argv[1]), sys.argv[2]
pins = dict(l.strip().split('==') for l in open(req) if l.strip() and not l.startswith('#'))
official = {}
for name, ver in sorted(pins.items()):
    meta = json.load(urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{ver}/json', timeout=30))
    official.update({u['filename']: u['digests']['sha256'] for u in meta['urls']})
files = sorted(wheels.iterdir()); ok = len(files) == len(pins)
for whl in files:
    got = hashlib.sha256(whl.read_bytes()).hexdigest(); ref = official.get(whl.name)
    ok &= got == ref
    print(f'{whl.name} {got} pypi={ref} {"OK" if got == ref else "MISMATCH"}')
sys.exit(0 if ok else 1)
EOF
  echo "wheel digests vs PyPI: $out.pypi_digests.txt (outside inbound/, for RUGGER 02)"
  (cd "$out" && find . -type f ! -path ./INBOUND_SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum > "$out.sums" && mv "$out.sums" INBOUND_SHA256SUMS)
  (cd "$out" && find . -type f | sed 's|^\./||' | LC_ALL=C sort > ../NAMES.txt)
  echo "INBOUND_SHA256SUMS sha256 = $(sha "$out/INBOUND_SHA256SUMS")  (to be anchored by RUGGER 02; NAMES.txt -> owner)"
  echo "CODE_COMMIT for the VM metadata = $commit" ;;

put)
  [ $# = 3 ] || die "usage: put BUCKET OUT_DIR"
  (cd "$3" && find . -type f | sed 's|^\./||' | LC_ALL=C sort) > "$3.names"
  while IFS= read -r name; do
    enc=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote("inbound/"+sys.argv[1],safe=""))' "$name")
    code=$(curl -sS -X POST -H 'Content-Type: application/octet-stream' --upload-file "$3/$name" -o /dev/null -w '%{http_code}' \
           "https://storage.googleapis.com/upload/storage/v1/b/$2/o?uploadType=media&name=$enc")
    echo "PUT inbound/$name http=$code sha256=$(sha "$3/$name")"; [ "$code" = 200 ] || die "upload_failed:$name"
  done < "$3.names"; rm "$3.names" ;;

get)
  [ $# = 3 ] || die "usage: get BUCKET DEST_DIR"; mkdir -p "$3"
  for name in RUN_LOG.txt RESULT.json DAYJ_STATE.json dayj_cloud_out.tar identity.json SELFCHECK.json; do
    code=$(curl -sS -o "$3/$name" -w '%{http_code}' "https://storage.googleapis.com/storage/v1/b/$2/o/outbound%2F$name?alt=media")
    if [ "$code" = 200 ]; then echo "GET outbound/$name sha256=$(sha "$3/$name")"; else rm -f "$3/$name"; echo "absent outbound/$name http=$code"; fi
  done
  [ -f "$3/RUN_LOG.txt" ] && [ -f "$3/RESULT.json" ] || die "run_log_or_result_missing"
  echo "next: RUGGER 02 checks RESULT.json out_tar_sha256 against dayj_cloud_out.tar, then every digest (C3)" ;;

upload)
  [ $# = 3 ] || die "usage: upload inbound_put_urls.tsv OUT_DIR"
  while IFS=$'\t' read -r name url; do
    case "$name" in ""|*..*|/*) die "bad_name:$name" ;; esac
    [ -f "$3/$name" ] || die "missing:$name"
    code=$(printf 'url = "%s"\n' "$url" | curl -sS -K - -X PUT -H 'Content-Type:' --upload-file "$3/$name" -o /dev/null -w '%{http_code}')
    echo "PUT $name http=$code sha256=$(sha "$3/$name")"; [ "$code" = 200 ] || die "upload_failed:$name"
  done < "$2"; rm -f "$2"; echo "signed-URL file removed" ;;

download)
  [ $# = 3 ] || die "usage: download outbound_get_urls.tsv DEST_DIR"
  mkdir -p "$3"
  while IFS=$'\t' read -r name url; do
    case "$name" in ""|*/*|.*) die "bad_name:$name" ;; esac
    code=$(printf 'url = "%s"\n' "$url" | curl -sS -K - -o "$3/$name" -w '%{http_code}')
    echo "GET $name http=$code sha256=$(sha "$3/$name")"; [ "$code" = 200 ] || die "download_failed:$name"
  done < "$2"; rm -f "$2"; echo "signed-URL file removed"
  echo "next: RUGGER 02 checks RESULT.json out_tar_sha256 against dayj_cloud_out.tar, then every digest (C3)" ;;
*) die "usage: prepare | upload | download" ;;
esac
