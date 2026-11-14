#!/bin/bash
# W1 D1 v2.6 — RUGGER 03 side of the transfer. Each mode needs the owner's GO (network to storage.googleapis.com,
# wheel download). No secret here: the proxy injects the owner's reduced (CAB) token; only names, HTTP codes and
# sha256 are printed, never a header (K-5).
#   prepare W1AUX_PKG CODE_REPO CODE_REF P0_REGISTRY CLOUD_PKG STEPS_JSON OUT_DIR NAME=DIR_OR_FILE...
#           (offline except `pip download`). NAME=DIR becomes data_NAME.tar, extracted on the VM as data/NAME/.
#   put     BUCKET OUT_DIR             token inbound : deposits every file of OUT_DIR under inbound/
#   state   BUCKET DEST_DIR            token relay or outbound : fetches the small per-step files
#   anchor  BUCKET STEP SHA256         token relay : deposits anchors/expect_STEP.txt (never overwrites)
#   get     BUCKET DEST_DIR            token outbound : fetches the final results
set -euo pipefail
die() { echo "STOP: $*"; exit 2; }
sha() { sha256sum "$1" | cut -d' ' -f1; }
STEPS="gate export series trials evaluate ledger dossier"
TAR=(tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner)

case "${1:-}" in
prepare)
  [ $# -ge 9 ] || die "usage: prepare W1AUX_PKG CODE_REPO CODE_REF P0_REGISTRY CLOUD_PKG STEPS_JSON OUT_DIR NAME=DIR..."
  pkg=$2; repo=$3; ref=$4; reg=$5; cloud=$6; steps=$7; out=$8; shift 8
  [ ! -e "$out" ] || die "out_exists"; mkdir -p "$out/wheels"
  git -C "$repo" show-ref --verify --quiet "$ref" || die "not_a_ref:$ref"
  [ "$(git -C "$repo" rev-parse "$ref^{tree}")" = aff97638cd011bcc3dc2b2826d42a208eb855aed ] || die frozen_tree
  commit=$(git -C "$repo" rev-parse "$ref^{commit}")
  [ "$(sha "$reg")" = f1f26e366bec2cdc3093bf027617d453d6d7dfbdd4b721173c290433004f47de ] || die p0_registry
  m=$(cd "$pkg" && find w1aux -type f ! -path '*__pycache__*' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1)
  [ "$m" = 31222874e019e3c24a9cb8b39e40b1ca4c5b6e4dff9e4aca283abef54310ac86 ] || die "w1aux_manifest:$m"
  git -C "$repo" bundle create "$out/w1code.bundle" "$ref"
  "${TAR[@]}" --exclude='__pycache__' -cf "$out/w1aux_v74.tar" -C "$pkg" w1aux
  # the collected data, as they are (run directories with their manifests); never a checkpoint, never a pickle
  for pair in "$@"; do
    name=${pair%%=*}; src=${pair#*=}
    case "$name" in *[!a-z0-9_]*|"") die "bad_data_name:$name" ;; esac
    [ ! -e "$out/data_$name.tar" ] || die "duplicate_data_name:$name"
    if [ -d "$src" ]; then "${TAR[@]}" --exclude='*.pkl' -cf "$out/data_$name.tar" -C "$src" .
    elif [ -f "$src" ]; then "${TAR[@]}" -cf "$out/data_$name.tar" -C "$(dirname "$src")" "$(basename "$src")"
    else die "missing_data:$src"; fi
    tar -tf "$out/data_$name.tar" > "$out.list"; if grep -qE '\.pkl$' "$out.list"; then die "pickle_in_data_$name"; fi; rm "$out.list"
  done
  # R02 (d): no secret may leave in a data tar (manifests, states, call logs may keep an endpoint). The transaction
  # and signature segments are raw chain data: they are not scanned (a random match would be meaningless).
  python3 -I - "$out"/data_*.tar <<'EOF' || die secret_pattern_in_data
import gzip, re, sys, tarfile
pat = re.compile(rb'api[-_]?key=|[?&]key=|apikey|x-api-key"?\s*[:=]\s*"?[A-Za-z0-9]|helius-rpc\.com/\?|BEGIN [A-Z ]*PRIVATE', re.I)
segment = re.compile(r'(^|/)(tx|sig|chk)-[0-9]+\.jsonl\.gz$')
hits = []
for path in sys.argv[1:]:
    with tarfile.open(path) as tar:
        for m in tar:
            if m.name.rstrip('/').endswith('.env') or '/.env' in m.name:
                hits.append(path + ':' + m.name); continue
            if not m.isfile() or segment.search(m.name):
                continue
            data = tar.extractfile(m).read()
            if m.name.endswith('.gz'):
                try:
                    data = gzip.decompress(data)
                except (OSError, EOFError):
                    pass                               # not gzip after all: scan the raw bytes
            if pat.search(data):
                hits.append(path + ':' + m.name)
for h in hits:
    print('secret-like pattern in', h)          # the member name only, never the value
sys.exit(1 if hits else 0)
EOF
  # the step arguments and the anchored hashes the VM must find (written by RUGGER 03, anchored by RUGGER 02)
  python3 -I - "$steps" <<'EOF' || die bad_steps_json
import json, re, sys
plan = json.load(open(sys.argv[1]))
assert set(plan) == {'args', 'expect_files', 'expect_gate_json_sha256'}, sorted(plan)
assert set(plan['args']) <= {'selfcheck', 'gate', 'export', 'series', 'trials', 'evaluate', 'ledger', 'dossier'}
reserved = {'--step', '--out', '--s0', '--expect-sha', '--resume', '--checkpoint', '--memory-override-anchored'}
for step, args in plan['args'].items():
    assert isinstance(args, list) and all(type(a) is str and '\n' not in a and a not in reserved for a in args), step
hexa = re.compile(r'^[0-9a-f]{64}$')
assert plan['expect_files'] and all(hexa.match(v) and not k.startswith('/') and '..' not in k for k, v in plan['expect_files'].items())
assert hexa.match(plan['expect_gate_json_sha256'])
EOF
  cp "$steps" "$out/STEPS.json"
  cp "$reg" "$out/p0_trials.jsonl"; cp "$cloud/identity_check_v26.py" "$cloud/IDENTITY_REFERENCE_V26.json" "$out/"
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
  echo "INBOUND_SHA256SUMS sha256 = $(sha "$out/INBOUND_SHA256SUMS")  (to be anchored by RUGGER 02)"
  echo "CODE_COMMIT for the VM metadata = $commit" ;;

put)
  [ $# = 3 ] || die "usage: put BUCKET OUT_DIR"
  (cd "$3" && find . -type f | sed 's|^\./||' | LC_ALL=C sort) > "$3.names"
  while IFS= read -r name; do
    enc=$(python3 -c 'import sys,urllib.parse;print(urllib.parse.quote("inbound/"+sys.argv[1],safe=""))' "$name")
    code=$(curl -sS -X POST -H 'Content-Type: application/octet-stream' --upload-file "$3/$name" -o /dev/null -w '%{http_code}' \
           "https://storage.googleapis.com/upload/storage/v1/b/$2/o?uploadType=media&ifGenerationMatch=0&name=$enc")
    echo "PUT inbound/$name http=$code sha256=$(sha "$3/$name")"; [ "$code" = 200 ] || die "upload_failed:$name"
  done < "$3.names"; rm "$3.names" ;;

state)
  [ $# = 3 ] || die "usage: state BUCKET DEST_DIR"; mkdir -p "$3"
  for name in RUN_LOG.txt DAYJ_STATE.json SELFCHECK.json GATE.json identity.json; do
    code=$(curl -sS -o "$3/$name" -w '%{http_code}' "https://storage.googleapis.com/storage/v1/b/$2/o/outbound%2F$name?alt=media")
    if [ "$code" = 200 ]; then echo "GET outbound/$name sha256=$(sha "$3/$name")"; else rm -f "$3/$name"; echo "absent outbound/$name http=$code"; fi
  done ;;

anchor)
  [ $# = 4 ] || die "usage: anchor BUCKET STEP SHA256"
  case " $STEPS " in *" $3 "*) ;; *) die "bad_step:$3" ;; esac
  [[ "$4" =~ ^[0-9a-f]{64}$ ]] || die bad_sha256
  code=$(printf '%s\n' "$4" | curl -sS -X POST -H 'Content-Type: text/plain' --data-binary @- -o /dev/null -w '%{http_code}' \
         "https://storage.googleapis.com/upload/storage/v1/b/$2/o?uploadType=media&ifGenerationMatch=0&name=anchors%2Fexpect_$3.txt")
  echo "PUT anchors/expect_$3.txt http=$code"; [ "$code" = 200 ] || die "anchor_not_deposited:$3" ;;

get)
  [ $# = 3 ] || die "usage: get BUCKET DEST_DIR"; mkdir -p "$3"
  for name in RUN_LOG.txt RESULT.json DAYJ_STATE.json dayj_cloud_out.tar identity.json SELFCHECK.json GATE.json; do
    code=$(curl -sS -o "$3/$name" -w '%{http_code}' "https://storage.googleapis.com/storage/v1/b/$2/o/outbound%2F$name?alt=media")
    if [ "$code" = 200 ]; then echo "GET outbound/$name sha256=$(sha "$3/$name")"; else rm -f "$3/$name"; echo "absent outbound/$name http=$code"; fi
  done
  [ -f "$3/RUN_LOG.txt" ] && [ -f "$3/RESULT.json" ] || die "run_log_or_result_missing"
  echo "next: RUGGER 02 checks RESULT.json out_tar_sha256 against dayj_cloud_out.tar, then every digest (C3)" ;;
*) die "usage: prepare | put | state | anchor | get" ;;
esac
