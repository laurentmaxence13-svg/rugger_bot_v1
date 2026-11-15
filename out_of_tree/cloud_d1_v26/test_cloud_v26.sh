#!/bin/bash
# Offline tests of the v2.6 cloud package with STUB gcloud / curl / shutdown / sleep (no network, no Google account).
# Usage: bash test_cloud_v26.sh <python 3.12.3 x86_64> <git checkout holding a commit of tree aff97638> <ref of that commit>
#                                <w1aux v7.4 package dir (parent of w1aux/)>
# create_vm.sh: refusals, the exact commands issued, the three token boundaries.
# startup.sh: the real script runs against a local "bucket"; only dayj, metrics and the identity sample are
# replaced by recording doubles (they have their own tests): input checks, one step per anchor, pause and resume,
# final STOP, deadline, boots limit, cross-check of GATE.json, resume of trials.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); REAL_PY=$1; REPO=$2; REF=$3; W1AUX=$4
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
mkdir -p "$tmp/bin" "$tmp/bucket/inbound" "$tmp/bucket/outbound" "$tmp/bucket/anchors"
export CALLS="$tmp/calls.log" BUCKET_DIR="$tmp/bucket" STATE="$tmp"; : > "$CALLS"

# ------------------------------------------------------------------ stubs
cat > "$tmp/bin/gcloud" <<'STUB'
#!/bin/bash
echo "gcloud $*" >> "$CALLS"
local_path() { echo "$BUCKET_DIR/${1#gs://*/}"; }
case "$*" in
  "storage cp --quiet -r gs://"*) src=$(local_path "${5%/\*}"); cp -r "$src"/. "$6" ;;
  "storage cp --quiet gs://"*) src=$(local_path "$4"); [ -f "$src" ] || exit 1; cp "$src" "$5" ;;
  "storage cp --quiet "*) args=("$@"); dest=$(local_path "${args[-1]}")
                          if [[ "${args[-1]}" == */ ]]; then mkdir -p "$dest"; for f in "${args[@]:3:${#args[@]}-4}"; do cp "$f" "$dest/"; done
                          else mkdir -p "$(dirname "$dest")"; cp "${args[3]}" "$dest"; fi ;;
  "storage ls gs://"*"/anchors/expect_"*) [ -f "$(local_path "$3")" ] ;;
  *"buckets update"*"--lifecycle-file="*) for a in "$@"; do case "$a" in --lifecycle-file=*) cp "${a#--lifecycle-file=}" "$STATE/lifecycle.json" ;; esac; done ;;
  *"buckets describe"*"--format"*) printf 'enforced\tTrue\tUS-CENTRAL1\n' ;;
  # the fake Compute Engine stores the termination time it is given and returns it in ANOTHER notation of the same instant
  *"set-scheduling"*|*"instances create"*) [[ "$*" != *set-scheduling* ]] || [ -z "${FAKE_SET_FAIL-}" ] || exit 1
     for a in "$@"; do case "$a" in --termination-time=*) TZ=America/Los_Angeles date -d "${a#--termination-time=}" +%FT%T.000%:z > "$STATE/when" ;; esac; done
     rm -f "$STATE/started" ;;
  *"instances start"*) touch "$STATE/started" ;;
  *"instances describe"*"scheduling.terminationTime"*)
     if [ -e "$STATE/started" ] && [ -n "${FAKE_LOST_AFTER_START-}" ]; then echo
     elif [ -n "${FAKE_WHEN+x}" ]; then echo "$FAKE_WHEN"; else cat "$STATE/when" 2>/dev/null || true; fi ;;
  *"instances describe"*"value(status)"*) echo "${FAKE_STATUS-TERMINATED}" ;;
  *"get-serial-port-output"*) echo "${FAKE_SERIAL-startup-script: PAUSE: no_anchor_for_gate_within_180_minutes}" ;;
  *"instances describe"*"creationTimestamp"*) echo "${FAKE_CREATED-$(TZ=America/Los_Angeles date +%FT%T.000%:z)}" ;;
  *"instances describe"*"scheduling.instanceTerminationAction"*) echo "${FAKE_ACTION-DELETE}" ;;
  *"buckets describe"*) [ -f "$STATE/bucket_created" ] ;;
  *"buckets create"*) touch "$STATE/bucket_created" ;;
  *"service-accounts describe"*) exit 1 ;;
  *"service-accounts list"*) echo "${FAKE_SA_LEFT-}" ;;
  *"instances delete"*|*"service-accounts delete"*|*"disks delete"*|"storage rm "*) [ -z "${FAKE_GONE-}" ] ;;
  *"get-value account"*) echo owner@example.com ;;
  *"print-access-token"*) echo BASE-TOKEN ;;
  *) : ;;
esac
STUB
cat > "$tmp/bin/curl" <<'STUB'
#!/bin/bash
case "$*" in
  *metadata.google.internal*) attr=${@: -1}; attr=${attr##*/}; cat "$STATE/md/$attr" ;;
  *) echo "curl $*" >> "$CALLS"; cat > /dev/null; echo '{"access_token":"REDUCED-TOKEN"}' ;;
esac
STUB
printf '#!/bin/bash\necho "shutdown $*" >> "$CALLS"\n' > "$tmp/bin/shutdown"
printf '#!/bin/bash\nexit 0\n' > "$tmp/bin/sleep"
cat > "$tmp/fake_python" <<STUB
#!/bin/bash
case " \$* " in
  *" w1aux.dayj "*) exec $REAL_PY -I "$tmp/fake_dayj.py" "\$@" ;;
  *" w1aux.metrics "*) echo "metrics \$*" >> "\$CALLS"; exit 0 ;;
  *identity_check_v26.py*) cat "$here/IDENTITY_REFERENCE_V26.json" | tr -d '\n'; echo; exit 0 ;;
  *) exec $REAL_PY "\$@" ;;
esac
STUB
cat > "$tmp/fake_dayj.py" <<'STUB'
import hashlib, json, os, sys
args = sys.argv[1:]
step, out = args[args.index('--step') + 1], args[args.index('--out') + 1]
os.makedirs(out, exist_ok=True)
path = out + '/DAYJ_STATE.json'
state = json.load(open(path)) if os.path.exists(path) else {'steps': {}}
open(os.environ['CALLS'], 'a').write('dayj ' + ' '.join(args[args.index('--step'):]) + '\n')
if step in state['steps']:
    sys.exit('step_already_done:' + step)
if step == 'selfcheck':
    json.dump({'sha256sums_sha256': '4aee76a3573344b37646202441c8b57c9fad0492d0674145691252dafbe85149'}, open(out + '/SELFCHECK.json', 'w'))
if step == 'gate':
    open(out + '/GATE.json', 'w').write('{"gate": "the same on both machines"}')
state['steps'][step] = {'digest': hashlib.sha256(step.encode()).hexdigest(), 'outputs': {}}
json.dump(state, open(path, 'w'))
STUB
chmod +x "$tmp/bin/"* "$tmp/fake_python"
export PATH="$tmp/bin:$PATH"
digest() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

# ------------------------------------------------------------------ A. create_vm.sh
for cmd in setup "token inbound" launch "anchor gate $(digest x)" start status teardown; do
  out=$(bash "$here/create_vm.sh" $cmd 2>&1) && fail "unfilled $cmd ran"; [[ "$out" == *"fill every __FILL value first"* ]] || fail "unfilled: $out"
done
[ ! -s "$CALLS" ] || fail "a command was issued while unfilled"
fill() { sed -e 's/__FILL: owner-project-id__/my-project-123/' -e 's/__FILL: owner-private-bucket__/my-bucket/' \
             -e 's/__FILL: ubuntu-2404-noble-amd64-vYYYYMMDD__/ubuntu-2404-noble-amd64-v20261101/' \
             -e "s/__FILL: n2-highmem-16 or n2-highmem-32 (sized by RUGGER 02 on the exported signature count)__/$1/" \
             -e "s/__FILL: RFC 3339 UTC time at which the VM is deleted whatever happens (at most 48 h ahead), e.g. 2026-11-17T12:00:00Z__/$2/" \
             -e "s/__FILL: sha256 of INBOUND_SHA256SUMS, as anchored by RUGGER 02__/$(digest sums)/" \
             -e 's/__FILL: commit whose tree is aff97638 (R03 c0199a3...)__/0123456789abcdef0123456789abcdef01234567/' "$here/create_vm.sh"; }
SOON=$(date -u -d '+40 hours' +%FT%TZ)
fill n2-highmem-16 "$SOON" > "$tmp/vm.sh"; grep -q __FILL "$tmp/vm.sh" | grep -v '^#' && fail "a field is left"
fill n2-standard-4 "$SOON" > "$tmp/bad1.sh"; out=$(bash "$tmp/bad1.sh" launch 2>&1) && fail "bad machine ran"; [[ "$out" == *"bad MACHINE"* ]] || fail "$out"
fill n2-highmem-16 tomorrow > "$tmp/bad2.sh"; out=$(bash "$tmp/bad2.sh" setup 2>&1) && fail "bad deadline ran"; [[ "$out" == *"bad DEADLINE"* ]] || fail "$out"
[ ! -s "$CALLS" ] || fail "a command was issued before the checks"
bash "$tmp/vm.sh" setup > "$tmp/out" || fail "setup: $(cat "$tmp/out")"
grep -q "buckets create gs://my-bucket --location=us-central1 --uniform-bucket-level-access --public-access-prevention" "$CALLS" || fail "bucket flags"
grep -q "buckets update gs://my-bucket --lifecycle-file=/tmp/lc.json" "$CALLS" || fail "lifecycle of the dedicated bucket"
[ "$(cat "$tmp/lifecycle.json")" = '{"rule":[{"action":{"type":"Delete"},"condition":{"age":7}}]}' ] || fail "lifecycle rule is not: delete after 7 days"
grep -Eq "keys create|projects add-iam-policy-binding|allUsers|allAuthenticatedUsers|compute instances" "$CALLS" && fail "forbidden command in setup"
for kind in inbound outbound relay; do
  : > "$CALLS"; out=$(bash "$tmp/vm.sh" token $kind)
  [[ "$out" == *REDUCED-TOKEN* && "$out" != *BASE-TOKEN* ]] || fail "token output $kind"
  grep -q "print-access-token --impersonate-service-account=w1-url-signer@my-project-123.iam.gserviceaccount.com" "$CALLS" || fail "impersonation"
  rules=$(grep -o 'inRole:roles/storage.object[A-Za-z]*' "$CALLS" | sort | tr '\n' ' ')
  prefixes=$(grep -o 'objects/[a-z]*/' "$CALLS" | sort | tr '\n' ' ')
  case $kind in
    inbound) [ "$rules" = "inRole:roles/storage.objectCreator " ] && [ "$prefixes" = "objects/inbound/ " ] || fail "inbound boundary: $rules $prefixes" ;;
    outbound) [ "$rules" = "inRole:roles/storage.objectViewer " ] && [ "$prefixes" = "objects/outbound/ " ] || fail "outbound boundary: $rules $prefixes" ;;
    relay) [ "$rules" = "inRole:roles/storage.objectCreator inRole:roles/storage.objectViewer " ] && [ "$prefixes" = "objects/anchors/ objects/outbound/ " ] || fail "relay boundary: $rules $prefixes" ;;
  esac
done
out=$(bash "$tmp/vm.sh" token both 2>&1) && fail "unknown token kind"
: > "$CALLS"; out=$(bash "$tmp/vm.sh" launch) || fail "launch: $out"
[[ "$out" == *"automatic deletion confirmed"* ]] || fail "launch does not confirm the automatic deletion"
line=$(grep "compute instances create" "$CALLS")
for want in "--machine-type=n2-highmem-16" "--boot-disk-size=200GB" "--no-address" "--termination-time=$SOON" \
            "--instance-termination-action=DELETE" "--shielded-secure-boot" "wait_minutes=180" "deadline=$SOON" \
            "block-project-ssh-keys=TRUE" "inbound_sums_sha256=$(digest sums)"; do
  [[ "$line" == *"$want"* ]] || fail "launch lacks $want"
done
grep -q "compute instances delete" "$CALLS" && fail "a confirmed VM was deleted"
# the automatic deletion is checked on the created VM: not set, or another action -> the VM is deleted at once
for bad in "FAKE_WHEN=" "FAKE_ACTION=STOP" "FAKE_WHEN=$(date -u -d '+41 hours' +%FT%TZ)" "FAKE_WHEN=some day"; do
  : > "$CALLS"; out=$(env "$bad" bash "$tmp/vm.sh" launch 2>&1) && fail "unconfirmed launch accepted ($bad)"
  [[ "$out" == *automatic_deletion_not_confirmed_vm_deleted* ]] || fail "$bad: $out"
  grep -q "compute instances delete w1-eval --zone=us-central1-a --quiet" "$CALLS" || fail "$bad: VM not deleted"
done
# the deadline must be ahead, and at most 48 h ahead: nothing is created otherwise
for when in "$(date -u -d '+49 hours' +%FT%TZ)" "$(date -u -d '-1 hour' +%FT%TZ)"; do
  fill n2-highmem-16 "$when" > "$tmp/late.sh"; : > "$CALLS"
  out=$(bash "$tmp/late.sh" launch 2>&1) && fail "deadline $when accepted"; [[ "$out" == *DEADLINE_* ]] || fail "$out"
  [ ! -s "$CALLS" ] || fail "something was created with a bad deadline"
done
[[ "$line" != *max-run-duration* && "$line" != *chain_mode* && "$line" != *start_step* ]] || fail "old launch option"
# start (R02 C-1): a stop clears the automatic deletion, so it is set again and checked BEFORE the VM starts
bash "$tmp/vm.sh" launch > /dev/null; : > "$CALLS"; rm -f "$tmp/when"          # the stop has cleared it
out=$(bash "$tmp/vm.sh" start) || fail "start: $out"
[[ "$out" == *"automatic deletion confirmed (start)"* ]] || fail "start does not confirm the automatic deletion"
grep -q "compute instances set-scheduling w1-eval --zone=us-central1-a --termination-time=$SOON --instance-termination-action=DELETE" "$CALLS" || fail "start does not set the automatic deletion again"
[ "$(grep -n "set-scheduling" "$CALLS" | cut -d: -f1)" -lt "$(grep -n "compute instances start" "$CALLS" | cut -d: -f1)" ] || fail "the VM starts before its automatic deletion is set"
[ "$(grep -c "scheduling.terminationTime" "$CALLS")" = 2 ] || fail "start must read the scheduling before AND after the start"
grep -q "compute instances delete" "$CALLS" && fail "a confirmed VM was deleted by start"
# not set, refused, another action, another instant, unreadable: the VM is NOT started
for bad in "FAKE_SET_FAIL=1" "FAKE_WHEN=" "FAKE_ACTION=STOP" "FAKE_WHEN=$(date -u -d '+41 hours' +%FT%TZ)" "FAKE_WHEN=some day" \
           "FAKE_CREATED=$(date -u -d '-9 hours' +%FT%TZ)" "FAKE_CREATED=some day" \
           "FAKE_STATUS=RUNNING" "FAKE_STATUS=" "FAKE_SERIAL=startup-script: STOP: rc=1"; do
  : > "$CALLS"; out=$(env "$bad" bash "$tmp/vm.sh" start 2>&1) && fail "unsafe start accepted ($bad)"
  [[ "$out" == *no_restart* ]] || fail "$bad: $out"
  grep -q "compute instances start" "$CALLS" && fail "$bad: the VM was started"
  if [[ "$bad" == FAKE_CREATED* || "$bad" == FAKE_STATUS* || "$bad" == FAKE_SERIAL* ]]; then grep -q "set-scheduling" "$CALLS" && fail "$bad: the scheduling was touched"; fi
done
# set before the start but gone after it: the VM is deleted at once
: > "$CALLS"; out=$(FAKE_LOST_AFTER_START=1 bash "$tmp/vm.sh" start 2>&1) && fail "start accepted a lost automatic deletion"
[[ "$out" == *automatic_deletion_lost_after_start_vm_deleted* ]] || fail "lost after start: $out"
grep -q "compute instances delete w1-eval --zone=us-central1-a --quiet" "$CALLS" || fail "lost after start: VM not deleted"
# a past deadline: no restart, nothing issued
fill n2-highmem-16 "$(date -u -d '-1 hour' +%FT%TZ)" > "$tmp/late.sh"; : > "$CALLS"
out=$(bash "$tmp/late.sh" start 2>&1) && fail "start after the deadline accepted"; [[ "$out" == *DEADLINE_is_in_the_past_no_restart* ]] || fail "$out"
[ ! -s "$CALLS" ] || fail "start issued a command after the deadline"
: > "$CALLS"
out=$(bash "$tmp/vm.sh" anchor selfcheck "$(digest x)" 2>&1) && fail "anchor for selfcheck"
out=$(bash "$tmp/vm.sh" anchor gate nothex 2>&1) && fail "bad sha accepted"; [[ "$out" == *bad_sha256* ]] || fail "$out"
[ ! -s "$CALLS" ] || fail "anchor issued commands before its checks"
bash "$tmp/vm.sh" anchor gate "$(digest selfcheck)" > /dev/null
[ "$(cat "$tmp/bucket/anchors/expect_gate.txt")" = "$(digest selfcheck)" ] || fail "anchor content"
out=$(bash "$tmp/vm.sh" anchor gate "$(digest other)" 2>&1) && fail "anchor overwritten"; [[ "$out" == *anchor_already_deposited* ]] || fail "$out"
rm "$tmp/bucket/anchors/expect_gate.txt"
: > "$CALLS"; bash "$tmp/vm.sh" teardown > /dev/null
grep -q "storage rm -r gs://my-bucket/inbound gs://my-bucket/outbound gs://my-bucket/anchors" "$CALLS" || fail "teardown prefixes"
grep -Eq "storage rm -r gs://my-bucket( |$)|buckets delete|w1-backup" "$CALLS" && fail "teardown touches the backup or the bucket"
# teardown may be run again (or after the automatic deletion): what is already gone is skipped, the checks still run
out=$(FAKE_GONE=1 bash "$tmp/vm.sh" teardown 2>&1) || fail "teardown fails when everything is already gone: $out"
[[ "$out" == *"teardown OK"* ]] || fail "second teardown does not conclude"
if out=$(FAKE_SA_LEFT=w1-eval-sa@p.iam.gserviceaccount.com bash "$tmp/vm.sh" teardown 2>&1); then fail "teardown accepts a remaining service account"; fi
[[ "$out" == *service_account_still_present* ]] || fail "wrong teardown refusal: $out"
# the owner procedure gives the sha256 of the two scripts to check after the upload: they must be the real ones
for f in create_vm.sh startup.sh; do
  grep -q "\`$f\` : \`$(sha256sum "$here/$f" | cut -d' ' -f1)\`" "$here/MARCHE_A_SUIVRE_PROPRIETAIRE.md" || fail "owner procedure: wrong sha256 for $f"
done
echo "A. create_vm.sh OK"

# ------------------------------------------------------------------ B. startup.sh
build_inbound() {      # $1 = destination
  local d=$1; rm -rf "$d"; mkdir -p "$d/wheels" "$tmp/src/launch" "$tmp/src/sol"
  git -C "$REPO" bundle create "$d/w1code.bundle" "$REF" 2> /dev/null
  tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner --exclude='__pycache__' -cf "$d/w1aux_v74.tar" -C "$W1AUX" w1aux
  echo '{"complete": true, "window": "launch"}' > "$tmp/src/launch/manifest.json"; echo x > "$tmp/src/launch/tx-000001.jsonl.gz"
  echo '{"complete": true, "window": "sol"}' > "$tmp/src/sol/manifest.json"
  tar -cf "$d/data_launchlab.tar" -C "$tmp/src/launch" .; tar -cf "$d/data_sol_usd.tar" -C "$tmp/src/sol" .
  mkdir -p "$tmp/whl/harmless_pkg"; echo "X = 1" > "$tmp/whl/harmless_pkg/__init__.py"
  (cd "$tmp/whl" && $REAL_PY -m zipfile -c "$d/wheels/harmless_pkg-1.0-py3-none-any.whl" harmless_pkg)
  cp "$here/identity_check_v26.py" "$here/IDENTITY_REFERENCE_V26.json" "$d/"; echo registry > "$d/p0_trials.jsonl"
  cat > "$d/STEPS.json" <<JSON
{"args": {"selfcheck": ["--workers", "{workers}"],
          "gate": ["--window-dir", "{data}/launchlab", "--summary-sha256", "$(digest summary)"],
          "export": ["--window-dir", "{data}/launchlab", "--other-run", "{data}/sol_usd"],
          "series": ["--sol-usd-dir", "{data}/sol_usd"], "trials": ["--workers", "{workers}"],
          "evaluate": ["--registry", "{registry}"]},
 "expect_files": {"data/launchlab/manifest.json": "$(sha256sum "$tmp/src/launch/manifest.json" | cut -d' ' -f1)",
                  "data/sol_usd/manifest.json": "$(sha256sum "$tmp/src/sol/manifest.json" | cut -d' ' -f1)"},
 "expect_gate_json_sha256": "${GATE_SHA:-$(printf '%s' '{"gate": "the same on both machines"}' | sha256sum | cut -d' ' -f1)}"}
JSON
}
sums() { (cd "$1" && find . -type f ! -path ./INBOUND_SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum > INBOUND_SHA256SUMS); }
new_vm() {             # a fresh "VM": metadata, empty disk, the given inbound directory as the bucket's inbound/
  rm -rf "$tmp/w1" "$tmp/md" "$tmp/bucket/outbound" "$tmp/bucket/anchors" "$tmp/bucket/inbound"
  mkdir -p "$tmp/md" "$tmp/bucket/outbound" "$tmp/bucket/anchors"; cp -r "$1" "$tmp/bucket/inbound"
  echo my-bucket > "$tmp/md/bucket"; sha256sum "$1/INBOUND_SHA256SUMS" | cut -d' ' -f1 > "$tmp/md/inbound_sums_sha256"
  echo 467275745 > "$tmp/md/s0"; echo 8 > "$tmp/md/workers"; echo 3 > "$tmp/md/wait_minutes"
  echo "${DEADLINE:-2099-01-01T00:00:00Z}" > "$tmp/md/deadline"; git -C "$REPO" rev-parse "$REF^{commit}" > "$tmp/md/code_commit"
  : > "$CALLS"
}
boot() { W1_ROOT="$tmp/w1" W1_PYTHON="$tmp/fake_python" bash "$here/startup.sh" > "$tmp/boot.out" 2>&1; }
log() { cat "$tmp/w1/RUN_LOG.txt"; }
expect_stop() { boot && fail "$1: the boot did not fail"; log | grep -q "STOP: $1" || fail "expected STOP $1, got: $(log | tail -5)"; grep -q shutdown "$CALLS" || fail "$1: no shutdown"; }
anchor() { for s in "$@"; do case $s in gate) p=selfcheck ;; export) p=gate ;; series) p=export ;; trials) p=series ;; evaluate) p=trials ;; ledger) p=evaluate ;; dossier) p=ledger ;; esac
           digest $p > "$tmp/bucket/anchors/expect_$s.txt"; done; }

build_inbound "$tmp/inbound"; sums "$tmp/inbound"
# B1. first boot: inputs, identity, selfcheck, then no anchor -> PAUSE (exit 0), state published, VM powered off
new_vm "$tmp/inbound"; boot || fail "boot 1: $(log | tail -8)"
log | grep -q "PAUSE: no_anchor_for_gate_within_3_minutes" || fail "no pause: $(log | tail -5)"
[ "$(grep -c '^dayj ' "$CALLS")" = 1 ] && grep -q "^dayj --step selfcheck --out $tmp/w1/dayj --s0 467275745 --workers 8$" "$CALLS" || fail "selfcheck call: $(grep '^dayj' "$CALLS")"
for f in identity.json SELFCHECK.json DAYJ_STATE.json RUN_LOG.txt; do [ -f "$tmp/bucket/outbound/$f" ] || fail "outbound lacks $f"; done
grep -q "shutdown -h now" "$CALLS" || fail "no shutdown after the pause"
[ -f "$tmp/w1/data/launchlab/manifest.json" ] && [ -f "$tmp/w1/site/harmless_pkg/__init__.py" ] && [ -f "$tmp/w1/READY" ] || fail "inputs not unpacked"
[ "$(git -C "$tmp/w1/code" rev-parse 'HEAD^{tree}')" = aff97638cd011bcc3dc2b2826d42a208eb855aed ] || fail "frozen tree on the VM"
# B2. two anchors -> two steps with the anchored digest and the expanded arguments, then PAUSE again; inputs not fetched twice
anchor gate export; : > "$CALLS"; boot || fail "boot 2: $(log | tail -8)"
grep -q "^dayj --step gate --out $tmp/w1/dayj --s0 467275745 --expect-sha $(digest selfcheck) --window-dir $tmp/w1/data/launchlab --summary-sha256 $(digest summary)$" "$CALLS" || fail "gate call: $(grep '^dayj' "$CALLS")"
grep -q "^dayj --step export --out $tmp/w1/dayj --s0 467275745 --expect-sha $(digest gate) --window-dir $tmp/w1/data/launchlab --other-run $tmp/w1/data/sol_usd$" "$CALLS" || fail "export call"
[ "$(grep -c '^dayj ' "$CALLS")" = 2 ] || fail "more than the anchored steps ran"
grep -q "inbound" "$CALLS" && fail "inputs fetched again"
log | grep -q "PAUSE: no_anchor_for_series_within_3_minutes" || fail "no second pause"
[ -f "$tmp/bucket/outbound/GATE.json" ] || fail "GATE.json not published"
# B3. every anchor -> the chain ends: metrics, the output tar without checkpoint, RESULT.json; a later boot does nothing
anchor series trials evaluate ledger dossier; mkdir -p "$tmp/w1/dayj/checkpoint"; echo p > "$tmp/w1/dayj/checkpoint/x.pkl"
: > "$CALLS"; boot || fail "boot 3: $(log | tail -8)"
[ "$(grep -c '^dayj ' "$CALLS")" = 5 ] || fail "steps of boot 3: $(grep '^dayj' "$CALLS")"
grep -q "^dayj --step evaluate .*--expect-sha $(digest trials) --registry $tmp/w1/in/p0_trials.jsonl$" "$CALLS" || fail "evaluate call"
grep -q "^dayj --step trials .*--workers 8$" "$CALLS" || fail "trials call"
grep -q "^metrics " "$CALLS" || fail "metrics not run"
[ -f "$tmp/bucket/outbound/RESULT.json" ] && [ -f "$tmp/bucket/outbound/dayj_cloud_out.tar" ] && [ -f "$tmp/w1/DONE" ] || fail "final outputs"
tar -tf "$tmp/bucket/outbound/dayj_cloud_out.tar" | grep -qE 'checkpoint|\.pkl$' && fail "checkpoint in the output tar"
$REAL_PY -I -c "import json,hashlib,sys;r=json.load(open('$tmp/bucket/outbound/RESULT.json'));assert r['operational_trade'] is False and len(r['steps'])==8 and r['out_tar_sha256']==hashlib.sha256(open('$tmp/bucket/outbound/dayj_cloud_out.tar','rb').read()).hexdigest()" || fail "RESULT.json"
: > "$CALLS"; boot || fail "boot after the end"; log | grep -q "PAUSE: chain_already_done" || fail "rerun after the end"
grep -q '^dayj ' "$CALLS" && fail "a step ran after the end"
# B4. a GATE.json that differs from the session's -> STOP, and the STOP is final
GATE_SHA=$(digest other) build_inbound "$tmp/in_gate"; sums "$tmp/in_gate"; new_vm "$tmp/in_gate"; anchor gate export
expect_stop gate_json_differs_from_the_session
: > "$CALLS"; boot && fail "boot after a STOP ran"; log | grep -q "STOP: previous_boot_stopped:gate_json_differs_from_the_session" || fail "STOP not final"
grep -q '^dayj ' "$CALLS" && fail "a step ran after a STOP"
# B5. a bad anchor, a past deadline, too many boots
new_vm "$tmp/inbound"; echo "not a digest" > "$tmp/bucket/anchors/expect_gate.txt"; expect_stop bad_anchor_for_gate
DEADLINE=2020-01-01T00:00:00Z new_vm "$tmp/inbound"; expect_stop past_deadline; grep -q '^dayj ' "$CALLS" && fail "ran past the deadline"
new_vm "$tmp/inbound"; mkdir -p "$tmp/w1"; echo 12 > "$tmp/w1/BOOTS"; expect_stop too_many_boots
new_vm "$tmp/inbound"; echo 64 > "$tmp/md/workers"; expect_stop "bad_workers:64"
# B6. inputs that are not exactly the anchored ones
tamper() { rm -rf "$tmp/t"; cp -r "$tmp/inbound" "$tmp/t"; }
tamper; echo extra > "$tmp/t/extra.txt"; new_vm "$tmp/t"; expect_stop inbound_unlisted_or_missing_files
tamper; echo changed >> "$tmp/t/p0_trials.jsonl"; new_vm "$tmp/t"; expect_stop inbound_file_hash_mismatch
tamper; new_vm "$tmp/t"; echo "$(digest wrong)" > "$tmp/md/inbound_sums_sha256"; expect_stop inbound_sums_sha256_mismatch
tamper; ln -s /etc/hostname "$tmp/t/link"; new_vm "$tmp/t"; expect_stop inbound_non_regular_file
tamper; mkdir -p "$tmp/p"; echo p > "$tmp/p/model.pkl"; tar -cf "$tmp/t/data_extra.tar" -C "$tmp/p" .; sums "$tmp/t"; new_vm "$tmp/t"; expect_stop "pickle_in_data_extra.tar"
tamper; $REAL_PY -I -c "
import io, tarfile
with tarfile.open('$tmp/t/data_extra.tar', 'w') as tar:
    info = tarfile.TarInfo('../escape.txt'); info.size = 1; tar.addfile(info, io.BytesIO(b'x'))"
sums "$tmp/t"; new_vm "$tmp/t"; expect_stop "unsafe_path_in_data_extra.tar"
tamper; $REAL_PY -I -c "
import tarfile
with tarfile.open('$tmp/t/data_extra.tar', 'w') as tar:
    info = tarfile.TarInfo('link'); info.type = tarfile.SYMTYPE; info.linkname = '/etc/passwd'; tar.addfile(info)"
sums "$tmp/t"; new_vm "$tmp/t"; expect_stop "non_regular_member_in_data_extra.tar"
tamper; mkdir -p "$tmp/o/other"; echo x > "$tmp/o/other/__init__.py"; tar -rf "$tmp/t/w1aux_v74.tar" -C "$tmp/o" other; sums "$tmp/t"; new_vm "$tmp/t"; expect_stop w1aux_tar_outside_w1aux
tamper; mkdir -p "$tmp/o2/w1aux"; echo "# changed" > "$tmp/o2/w1aux/extra.py"; tar -rf "$tmp/t/w1aux_v74.tar" -C "$tmp/o2" w1aux/extra.py; sums "$tmp/t"; new_vm "$tmp/t"; expect_stop w1aux_manifest
tamper; mkdir -p "$tmp/w2"; echo "X = 1" > "$tmp/w2/json.py"; (cd "$tmp/w2" && $REAL_PY -m zipfile -c "$tmp/t/wheels/bad-1.0-py3-none-any.whl" json.py); sums "$tmp/t"; new_vm "$tmp/t"; expect_stop wheel_shadows_a_module
tamper; sed -i 's/"data\/sol_usd\/manifest.json": "[0-9a-f]*"/"data\/sol_usd\/manifest.json": "'"$(digest no)"'"/' "$tmp/t/STEPS.json"; sums "$tmp/t"; new_vm "$tmp/t"; expect_stop anchored_file_differs
tamper; sed -i 's/"--other-run", /"--out", /' "$tmp/t/STEPS.json"; sums "$tmp/t"; new_vm "$tmp/t"; anchor gate export; expect_stop "bad_step_arguments:export"
# B7. trials already started (interrupted VM): the step is resumed, not restarted
new_vm "$tmp/inbound"; boot; anchor gate export series trials
$REAL_PY -I -c "
import json; p='$tmp/w1/dayj/DAYJ_STATE.json'; s=json.load(open(p)); s['trials_started']={'registered_at': 'x'}; json.dump(s, open(p, 'w'))"
: > "$CALLS"; boot || fail "resume boot: $(log | tail -5)"
grep -q "^dayj --step trials .*--workers 8 --resume$" "$CALLS" || fail "trials not resumed: $(grep 'step trials' "$CALLS")"
echo "B. startup.sh OK"
echo "ALL OK"
