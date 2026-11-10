#!/bin/bash
# W1 D1 cloud run — startup script of the GCE VM (runs once, as root, at boot). NOT EXECUTED WITHOUT OWNER GO.
# Inputs come ONLY from the private bucket; every file is checked against INBOUND_SHA256SUMS, whose own
# sha256 is given in the instance metadata (so a changed bucket object stops the run).
# The VM has no external IP: it reaches only Google APIs (Private Google Access). No secret is read or written;
# authentication is the VM's dedicated service account (bucket-scoped role), no key file.
# Offline computation only: HISTORICAL_REPLAY, research, never an order, never a signature.
set -euo pipefail
md() { curl -fsS -H 'Metadata-Flavor: Google' "http://metadata.google.internal/computeMetadata/v1/instance/attributes/$1"; }
BUCKET=$(md bucket); SUMS_SHA=$(md inbound_sums_sha256); S0=$(md s0); START=$(md start_step)
EXPECT=$(md expect_sha); WORKERS=$(md workers); CHAIN=$(md chain_mode)       # chain_mode: anchored | chained
PY=/usr/bin/python3; PY_CHECK="/usr/bin/python3 -I"; W=/opt/w1; LOG=$W/RUN_LOG.txt; mkdir -p $W/in $W/site; exec > >(tee -a $LOG) 2>&1
up() { gcloud storage cp --quiet "$@" "gs://$BUCKET/outbound/" || true; }
finish() { rc=$?; echo "EXIT rc=$rc at $(date -u +%FT%TZ)"; up $LOG; [ -f $W/RESULT.json ] && up $W/RESULT.json; sync; shutdown -h now; }
trap finish EXIT
stop() { echo "STOP: $*"; exit 3; }
echo "start $(date -u +%FT%TZ) start_step=$START chain=$CHAIN workers=$WORKERS"
[ -e $W/RUN_STARTED ] && stop second_boot_refused          # R02 N-2 / C2: one run per GO, never a silent rerun
touch $W/RUN_STARTED
case "$START" in none|trials|evaluate) ;; *) stop "bad_start_step:$START" ;; esac          # R02 V-1
case "$CHAIN" in anchored|chained) ;; *) stop "bad_chain_mode:$CHAIN" ;; esac
case "$WORKERS" in [1-9]|1[0-6]) ;; *) stop "bad_workers:$WORKERS" ;; esac

# 1. Inputs, hash-checked.
gcloud storage cp --quiet -r "gs://$BUCKET/inbound/*" $W/in/                                # R02 B-1: -r (wheels/)
cd $W/in
[ "$(sha256sum INBOUND_SHA256SUMS | cut -d' ' -f1)" = "$SUMS_SHA" ] || stop inbound_sums_sha256_mismatch
sha256sum --strict -c INBOUND_SHA256SUMS || stop inbound_file_hash_mismatch
# R02 B-4: the files present are EXACTLY the listed ones (+ the SUMS file); no symlink, no extra file.
diff <(find . -type f ! -path ./INBOUND_SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort) \
     <(sed -E 's/^[0-9a-f]{64} [ *]//' INBOUND_SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort) || stop inbound_unlisted_or_missing_files
[ -z "$(find . ! -type f ! -type d)" ] || stop inbound_non_regular_file
# R02 B-4: w1aux tar holds only w1aux/; R02 C4: no pickle in any inbound tar.
# (listings go to files first: with pipefail, `tar | grep -q` can hide a match through SIGPIPE)
tar -tf w1aux_v73.tar > $W/list_w1aux.txt; if grep -qvE '^w1aux(/|$)' $W/list_w1aux.txt; then stop w1aux_tar_outside_w1aux; fi
for t in w1aux_v73.tar dayj_out.tar; do
  if [ -f $t ]; then tar -tf $t > $W/list_$t.txt; if grep -qE '\.pkl$' $W/list_$t.txt; then stop "pickle_in_$t"; fi; fi
done
# R02 B-4: no wheel may provide a top-level name that shadows bot, w1aux, site hooks or the stdlib; no .pth.
$PY_CHECK - <<'EOF' || stop wheel_shadows_a_module
import sys, zipfile, glob
bad = {'bot', 'w1aux', 'tests', 'sitecustomize', 'usercustomize'} | set(sys.stdlib_module_names)
for whl in glob.glob('/opt/w1/in/wheels/*.whl'):
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
export PYTHONPATH=$W/w1aux_pkg:$W/code:$W/site RUGGER_NO_DOTENV=1 PYTHONDONTWRITEBYTECODE=1

# 4. Frozen code (git bundle of the commit whose tree is aff97638) and w1aux v7.3 (MANIFEST 63eb3412).
git init -q $W/code && git -C $W/code fetch -q $W/in/w1code.bundle '+refs/*:refs/bundle/*' && git -C $W/code checkout -q "$(md code_commit)"
[ "$(git -C $W/code rev-parse 'HEAD^{tree}')" = aff97638cd011bcc3dc2b2826d42a208eb855aed ] || stop frozen_tree
mkdir -p $W/w1aux_pkg && tar -xf $W/in/w1aux_v73.tar -C $W/w1aux_pkg
(cd $W/w1aux_pkg && find w1aux -type f ! -path '*__pycache__*' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1) > $W/w1aux_manifest.sha
[ "$(cat $W/w1aux_manifest.sha)" = 63eb3412a94483002a0a43833e73dad79e536be03254e5507c5464de0041c420 ] || stop w1aux_manifest

# 5. Machine equivalence BEFORE any W1 data is touched: dayj selfcheck (own dir) + synthetic identity sample.
cd $W/code
$PY -B -m w1aux.dayj --step selfcheck --out $W/cloud_selfcheck --s0 "$S0" --workers "$WORKERS"
$PY - <<'EOF' || stop selfcheck_sums
import json; d=json.load(open('/opt/w1/cloud_selfcheck/SELFCHECK.json'))
assert d['sha256sums_sha256'].startswith('4aee76a3'), d['sha256sums_sha256']
EOF
$PY -B $W/in/identity_check.py $W/idc | tail -1 > $W/identity.json
$PY - <<'EOF' || stop identity_sample
import json; got=json.load(open('/opt/w1/identity.json')); ref=json.load(open('/opt/w1/in/IDENTITY_REFERENCE.json'))
for k in ('w1_report_sha256','ledger_sha256','bundles_sums_sha256'): assert got[k]==ref[k], (k, got[k], ref[k])
EOF

# 6. W1 day-J steps from START, on the dayj directory produced in the R03 session (all earlier outputs are
#    re-hashed by dayj itself; identities and s0 must equal the session's, else dayj stops).
[ "$START" = none ] || { mkdir -p $W/dayj && tar -xf $W/in/dayj_out.tar -C $W/dayj; }
REG=$W/in/p0_trials.jsonl     # P0 registry f1f26e36 (hash-checked in step 1)
steps=(trials evaluate ledger dossier); go=0; prev_sha="$EXPECT"
for step in "${steps[@]}"; do
  [ "$step" = "$START" ] && go=1; [ $go = 1 ] || continue
  if [ "$CHAIN" = anchored ] && [ "$step" != "$START" ]; then          # wait for R02's anchor relayed by R03
    for i in $(seq 1 360); do gcloud storage cp --quiet "gs://$BUCKET/anchors/expect_$step.txt" $W/expect_$step.txt 2>/dev/null && break; sleep 30; done
    [ -s $W/expect_$step.txt ] || stop "no_anchor_for_$step"; prev_sha=$(tr -d ' \n' < $W/expect_$step.txt)
  fi
  extra=(); [ "$step" = evaluate ] && extra=(--registry "$REG")
  if [ "$step" = trials ]; then extra=(--workers "$WORKERS")                                    # R02 B-2
    $PY -c "import json,sys;sys.exit(0 if json.load(open('$W/dayj/DAYJ_STATE.json')).get('trials_started') else 1)" && extra+=(--resume)
  fi
  $PY -B -m w1aux.dayj --step "$step" --out $W/dayj --s0 "$S0" --expect-sha "$prev_sha" "${extra[@]}"
  prev_sha=$($PY -c "import json;print(json.load(open('$W/dayj/DAYJ_STATE.json'))['steps']['$step']['digest'])")
  echo "step $step digest $prev_sha"; up $W/dayj/DAYJ_STATE.json
done
if [ "$START" = none ]; then echo "equivalence-only run (start_step=none): PASS"; echo '{"equivalence":"PASS"}' > $W/RESULT.json; up $W/identity.json $W/cloud_selfcheck/SELFCHECK.json; exit 0; fi
$PY -B -m w1aux.metrics --w1-dir $W/dayj --s0 "$S0"

# 7. Outputs: the whole dayj directory (checkpoint excluded: resume data, pickle, never published) + result.
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner --exclude=./checkpoint --exclude='*.pkl' -cf $W/dayj_cloud_out.tar -C $W/dayj .
$PY - <<EOF
import hashlib, json
st=json.load(open('$W/dayj/DAYJ_STATE.json'))
json.dump(dict(steps={k: v['digest'] for k, v in st['steps'].items()}, identity=json.load(open('$W/identity.json')),
               out_tar_sha256=hashlib.sha256(open('$W/dayj_cloud_out.tar','rb').read()).hexdigest(),
               category='HISTORICAL_REPLAY', operational_trade=False), open('$W/RESULT.json','w'), indent=1, sort_keys=True)
EOF
tar -tf $W/dayj_cloud_out.tar > $W/list_out.txt; if grep -qE '\.pkl$' $W/list_out.txt; then stop pickle_in_outbound_tar; fi  # R02 C4
up $W/dayj_cloud_out.tar
echo "done $(date -u +%FT%TZ)"
