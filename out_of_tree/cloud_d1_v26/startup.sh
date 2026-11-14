#!/bin/bash
# W1 D1 v2.6 cloud run — startup script of the GCE VM (runs as root at EVERY boot). NOT EXECUTED WITHOUT OWNER GO.
# The whole post-collection chain with the FROZEN code, unchanged, ONE STEP AT A TIME (R02 d38f6580):
#   selfcheck -> gate -> export -> series -> trials -> evaluate -> ledger -> dossier
# Before each step but the first, the VM waits for anchors/expect_<step>.txt: the digest of the previous step as
# anchored by RUGGER 02. No anchor within wait_minutes: the VM powers off (PAUSE) and resumes at its next start.
# A STOP is final: the next boots refuse to run (no silent rerun, R02 N-2 / C2).
# Inputs come ONLY from the private bucket; every file is checked against INBOUND_SHA256SUMS, whose own sha256 is
# given in the instance metadata. No external IP: only Google APIs (Private Google Access). No secret is read or
# written; authentication is the VM's dedicated service account (bucket-scoped role), no key file.
# Offline computation only: HISTORICAL_REPLAY, research, never an order, never a signature.
set -euo pipefail
md() { curl -fsS -H 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
BUCKET=$(md bucket); SUMS_SHA=$(md inbound_sums_sha256); S0=$(md s0); WORKERS=$(md workers)
WAIT=$(md wait_minutes); DEADLINE=$(md deadline)
W=${W1_ROOT:-/opt/w1}; PY=${W1_PYTHON:-/usr/bin/python3}; PY_CHECK="$PY -I"      # the two overrides exist for offline tests only
LOG=$W/RUN_LOG.txt; mkdir -p $W/in $W/site $W/data; exec > >(tee -a $LOG) 2>&1
up() { gcloud storage cp --quiet "$@" "gs://$BUCKET/outbound/" || true; }
finish() {
  rc=$?; echo "EXIT rc=$rc at $(date -u +%FT%TZ)"
  [ $rc = 0 ] || [ -e $W/STOPPED ] || echo "rc=$rc" > $W/STOPPED          # any failure is final too
  up $LOG; [ -f $W/RESULT.json ] && up $W/RESULT.json; sync; shutdown -h now
}
trap finish EXIT
stop() { echo "STOP: $*"; echo "$*" > $W/STOPPED; exit 3; }
pause() { echo "PAUSE: $*"; exit 0; }
state() { $PY_CHECK -c "
import json, os, sys
p = '$W/dayj/DAYJ_STATE.json'
s = json.load(open(p)) if os.path.exists(p) else {'steps': {}}
print($1)"; }

boots=$(( $(cat $W/BOOTS 2>/dev/null || echo 0) + 1 )); echo $boots > $W/BOOTS
echo "boot $boots at $(date -u +%FT%TZ) workers=$WORKERS wait_minutes=$WAIT deadline=$DEADLINE"
[ ! -e $W/STOPPED ] || { echo "STOP: previous_boot_stopped:$(cat $W/STOPPED)"; exit 3; }
[ ! -e $W/DONE ] || pause "chain_already_done"
[ $boots -le 12 ] || stop too_many_boots
case "$WORKERS" in [1-9]|[12][0-9]|3[0-2]) ;; *) stop "bad_workers:$WORKERS" ;; esac          # R02 V-1
case "$WAIT" in [1-9]|[1-9][0-9]|[1-9][0-9][0-9]) ;; *) stop "bad_wait_minutes:$WAIT" ;; esac
[[ "$DEADLINE" =~ ^20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] || stop "bad_deadline"
[[ "$(date -u +%FT%TZ)" < "$DEADLINE" ]] || stop past_deadline
export PYTHONPATH=$W/w1aux_pkg:$W/code:$W/site RUGGER_NO_DOTENV=1 PYTHONDONTWRITEBYTECODE=1

if [ ! -e $W/READY ]; then
  # 1. Inputs, hash-checked.
  gcloud storage cp --quiet -r "gs://$BUCKET/inbound/*" $W/in/                              # R02 B-1: -r (wheels/)
  cd $W/in
  [ "$(sha256sum INBOUND_SHA256SUMS | cut -d' ' -f1)" = "$SUMS_SHA" ] || stop inbound_sums_sha256_mismatch
  sha256sum --strict -c INBOUND_SHA256SUMS || stop inbound_file_hash_mismatch
  # R02 B-4: the files present are EXACTLY the listed ones (+ the SUMS file); no symlink, no extra file.
  diff <(find . -type f ! -path ./INBOUND_SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort) \
       <(sed -E 's/^[0-9a-f]{64} [ *]//' INBOUND_SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort) || stop inbound_unlisted_or_missing_files
  [ -z "$(find . ! -type f ! -type d)" ] || stop inbound_non_regular_file
  # R02 B-4: the w1aux tar holds only w1aux/; R02 C4: no pickle in any tar; data tars hold relative regular paths only.
  # (listings go to files first: with pipefail, `tar | grep -q` can hide a match through SIGPIPE)
  tar -tf w1aux_v74.tar > $W/list_w1aux.txt; if grep -qvE '^w1aux(/|$)' $W/list_w1aux.txt; then stop w1aux_tar_outside_w1aux; fi
  for t in *.tar; do
    tar -tf "$t" > "$W/list_$t.txt"; if grep -qE '\.pkl$' "$W/list_$t.txt"; then stop "pickle_in_$t"; fi
    if grep -qE '(^/|(^|/)\.\.(/|$))' "$W/list_$t.txt"; then stop "unsafe_path_in_$t"; fi
    tar -tvf "$t" > "$W/long_$t.txt"; if grep -qvE '^[-d]' "$W/long_$t.txt"; then stop "non_regular_member_in_$t"; fi
  done
  # R02 B-4: no wheel may provide a top-level name that shadows bot, w1aux, site hooks or the stdlib; no .pth.
  $PY_CHECK - "$W/in/wheels" <<'EOF' || stop wheel_shadows_a_module
import sys, zipfile, glob
bad = {'bot', 'w1aux', 'tests', 'sitecustomize', 'usercustomize'} | set(sys.stdlib_module_names)
for whl in glob.glob(sys.argv[1] + '/*.whl'):
    for name in zipfile.ZipFile(whl).namelist():
        top = name.split('/')[0]
        if top.endswith(('.dist-info', '.data')):
            continue
        mod = top[:-3] if top.endswith('.py') else top.split('.')[0]
        if mod in bad or name.endswith('.pth'):
            raise SystemExit(f'{whl}: {name}')
EOF

  # 2. Interpreter: identities() pins CPython 3.12.3 x86_64 Linux (the R03 session's values).
  [ "$($PY -c 'import platform as p;print(p.python_implementation(),p.python_version(),p.machine(),p.system())')" = "CPython 3.12.3 x86_64 Linux" ] || stop python_identity

  # 3. Pinned wheels unpacked with the stdlib only (no pip, no network): requirements-dayj.txt lists them.
  for whl in $W/in/wheels/*.whl; do $PY -m zipfile -e "$whl" $W/site/; done

  # 4. Frozen code (git bundle of the commit whose tree is aff97638) and w1aux v7.4 (MANIFEST 31222874, R02 46da9df2).
  git init -q $W/code && git -C $W/code fetch -q $W/in/w1code.bundle '+refs/*:refs/bundle/*' && git -C $W/code checkout -q "$(md code_commit)"
  [ "$(git -C $W/code rev-parse 'HEAD^{tree}')" = aff97638cd011bcc3dc2b2826d42a208eb855aed ] || stop frozen_tree
  mkdir -p $W/w1aux_pkg && tar -xf $W/in/w1aux_v74.tar -C $W/w1aux_pkg
  (cd $W/w1aux_pkg && find w1aux -type f ! -path '*__pycache__*' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1) > $W/w1aux_manifest.sha
  [ "$(cat $W/w1aux_manifest.sha)" = 31222874e019e3c24a9cb8b39e40b1ca4c5b6e4dff9e4aca283abef54310ac86 ] || stop w1aux_manifest

  # 5. The collected data (never parsed here): data_<name>.tar -> data/<name>/ ; then the files RUGGER 02 anchored
  #    (run manifests, fetch summary, owner reading, study report) must have the sha256 listed in STEPS.json.
  for t in $W/in/data_*.tar; do
    name=$(basename "$t" .tar); name=${name#data_}
    case "$name" in *[!a-z0-9_]*|"") stop "bad_data_name:$name" ;; esac
    mkdir -p "$W/data/$name" && tar -xf "$t" -C "$W/data/$name"
  done
  $PY_CHECK - "$W" <<'EOF' || stop anchored_file_differs
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
plan = json.loads((root / 'in' / 'STEPS.json').read_text())
if set(plan) != {'args', 'expect_files', 'expect_gate_json_sha256'} or not plan['expect_files']:
    raise SystemExit('STEPS.json: unexpected keys')
for rel, want in sorted(plan['expect_files'].items()):
    path = (root / rel).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise SystemExit('missing or outside: ' + rel)
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            h.update(block)
    if h.hexdigest() != want:
        raise SystemExit('sha256 differs: ' + rel)
EOF

  # 6. Machine equivalence BEFORE any W1 data is parsed: the synthetic identity sample (three anchored digests
  #    that do not depend on the machine: bundles, report without its runtime record, ledger without the report sha).
  cd $W/code
  $PY -B $W/in/identity_check_v26.py $W/idc | tail -1 > $W/identity.json
  $PY_CHECK - "$W" <<'EOF' || stop identity_sample
import json, sys
got = json.load(open(sys.argv[1] + '/identity.json')); ref = json.load(open(sys.argv[1] + '/in/IDENTITY_REFERENCE_V26.json'))
for k in ('bundles_sums_sha256', 'w1_report_core_sha256', 'ledger_core_sha256'):      # machine-independent (v2.6)
    assert got[k] == ref[k], (k, got[k], ref[k])
EOF
  up $W/identity.json
  touch $W/READY
fi

# 7. The chain, one step per anchor. dayj re-hashes every earlier output, checks the identities and S0 at each
#    step, and refuses an --expect-sha that is not the digest of the previous step.
cd $W/code
REG=$W/in/p0_trials.jsonl     # P0 registry f1f26e36 (hash-checked in step 1)
for step in selfcheck gate export series trials evaluate ledger dossier; do
  [ "$(state "int('$step' in s['steps'])")" = 1 ] && continue
  [[ "$(date -u +%FT%TZ)" < "$DEADLINE" ]] || stop past_deadline
  expect=()
  if [ "$step" != selfcheck ]; then                     # wait for RUGGER 02's anchor of the previous step
    for i in $(seq 1 $((WAIT * 2))); do
      gcloud storage cp --quiet "gs://$BUCKET/anchors/expect_$step.txt" $W/expect_$step.txt 2>/dev/null && break; sleep 30
    done
    [ -s $W/expect_$step.txt ] || pause "no_anchor_for_${step}_within_${WAIT}_minutes"
    sha=$(tr -d ' \n\r' < $W/expect_$step.txt)
    [[ "$sha" =~ ^[0-9a-f]{64}$ ]] || stop "bad_anchor_for_$step"
    expect=(--expect-sha "$sha")
  fi
  $PY_CHECK - "$W" "$step" "$WORKERS" "$REG" > "$W/args_$step.txt" <<'EOF' || stop "bad_step_arguments:$step"
import json, sys
root, step, workers, registry = sys.argv[1:]
args = json.load(open(root + '/in/STEPS.json'))['args'].get(step, [])
reserved = {'--step', '--out', '--s0', '--expect-sha', '--resume', '--checkpoint', '--memory-override-anchored'}
if not isinstance(args, list) or any(type(a) is not str or '\n' in a or a in reserved for a in args):
    raise SystemExit('bad arguments for ' + step)
for a in args:
    print(a.replace('{data}', root + '/data').replace('{in}', root + '/in')
           .replace('{workers}', workers).replace('{registry}', registry))
EOF
  mapfile -t extra < "$W/args_$step.txt"
  if [ "$step" = trials ] && [ "$(state "int(bool(s.get('trials_started')))")" = 1 ]; then extra+=(--resume); fi   # R02 B-2
  echo "step $step starts at $(date -u +%FT%TZ)"
  $PY -B -m w1aux.dayj --step "$step" --out $W/dayj --s0 "$S0" "${expect[@]}" "${extra[@]}"
  echo "step $step digest $(state "s['steps']['$step']['digest']") at $(date -u +%FT%TZ)"
  if [ "$step" = selfcheck ]; then
    $PY_CHECK -c "import json;d=json.load(open('$W/dayj/SELFCHECK.json'));assert d['sha256sums_sha256'].startswith('4aee76a3'), d['sha256sums_sha256']" || stop selfcheck_sums
    up $W/dayj/SELFCHECK.json
  fi
  if [ "$step" = gate ]; then                           # R02 d38f6580: the same GATE.json as in the R03 session
    want=$($PY_CHECK -c "import json;print(json.load(open('$W/in/STEPS.json'))['expect_gate_json_sha256'])")
    [ "$(sha256sum $W/dayj/GATE.json | cut -d' ' -f1)" = "$want" ] || stop gate_json_differs_from_the_session
    up $W/dayj/GATE.json
  fi
  up $W/dayj/DAYJ_STATE.json $LOG
done
$PY -B -m w1aux.metrics --w1-dir $W/dayj --s0 "$S0"

# 8. Outputs: the whole dayj directory (checkpoint excluded: resume data, pickle, never published) + result.
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner --exclude=./checkpoint --exclude='*.pkl' -cf $W/dayj_cloud_out.tar -C $W/dayj .
$PY_CHECK - "$W" <<'EOF'
import hashlib, json, sys
root = sys.argv[1]
st = json.load(open(root + '/dayj/DAYJ_STATE.json'))
h = hashlib.sha256()
with open(root + '/dayj_cloud_out.tar', 'rb') as handle:
    for block in iter(lambda: handle.read(1 << 20), b''):
        h.update(block)
json.dump(dict(steps={k: v['digest'] for k, v in st['steps'].items()}, identity=json.load(open(root + '/identity.json')),
               out_tar_sha256=h.hexdigest(), category='HISTORICAL_REPLAY', operational_trade=False),
          open(root + '/RESULT.json', 'w'), indent=1, sort_keys=True)
EOF
tar -tf $W/dayj_cloud_out.tar > $W/list_out.txt; if grep -qE '\.pkl$' $W/list_out.txt; then stop pickle_in_outbound_tar; fi  # R02 C4
up $W/dayj_cloud_out.tar
touch $W/DONE
echo "done $(date -u +%FT%TZ)"
