#!/bin/bash
# livepaper 0.1.5 SETUP (R03), NOT armed. Usage: bash setup_livepaper015.sh <OUT_DIR (new)> <START (unix s)>
# Steps: prepare (offline) -> SEED_INPUT -> collect-gsfa (ONLY network step, read-only GSFA, new ledger L.json)
#        -> ordercheck (offline, GTFA = livesim pre-start pages 951b8479). Then R03 inscribes OUT/START/POOLS/SEED/OC
#        in launch_livepaper015_run.sh and chain_resume015.sh; R02 audits that delta; no run before R02's GO.
set -u
OUT=$1; START=$2
S=/tmp/claude-0/-home-user/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad
R=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run
P=$S/livepaper_9800986/out_of_tree/cpmm_pilot/livepaper015_pkg        # extraction of 9800986 (git archive)
MANIFEST=MANIFEST_livepaper_v0_1_5.txt; MANIFEST_SHA=9ac7089c8ee97ec49cf67896c666fa0ec57b248c619c0ecb38f11a0557c649f9
AUTH=$R/AUTORISATION_LIVEPAPER_V7.txt; AUTH_SHA=31dfed474aa18a6e463bae0bf1e16d465a8edc0da8ad15362d1019f51ba66050
PPF=$R/livepaper015_run/PYTHONPATH_015.txt; PPF_SHA=488b87735e688bd02e15da2d8d22af7398c554d6a6701d2ecde6902f9eda0a28
ELIG=$R/LIVESIM_ELIGIBLE032_20261125T144635Z/ELIGIBLE.json; ELIG_SHA=184576ea0358e8b619d1cb1d107eb82a93a94e67d5d87d204a8831c2b45b34a9
LISTL=$R/TIME1R_20261124T102126Z/LIST_L.json; LISTL_SHA=c96353b9f3c0bdb25fd1b7c8af85cf0c4efd66e84480d7850252b85d8a7d8ff3
PRE=$R/LIVESIM_20261125T113851Z; PRE_SUMS_SHA=951b84798db5b4a433389b7b3c01c3a3e0a367168d443f6c3b5507497bbf61c0
PY=/tmp/claude-0/-home-user-rugger-bot-v1/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad/venv312/bin/python
h(){ sha256sum "$1" | cut -d' ' -f1; }
[ -e "$OUT" ] && { echo "OUT_EXISTS: no call"; exit 3; }
mkdir -p "$OUT" || exit 3
{
  echo "setup $(date -u +%FT%TZ) out=$OUT start=$START"
  NOW=$(date -u +%s)
  case "$START" in ''|*[!0-9]*) echo "BAD_START: no call"; exit 4;; esac
  [ "$START" -lt $((NOW+300)) ] && { echo "START_TOO_CLOSE (< now+300 s): no call"; exit 4; }
  [ "$START" -gt $((NOW+10800)) ] && { echo "START_TOO_FAR (> now+3 h): no call"; exit 4; }
  ( cd $P && sha256sum -c $MANIFEST ) > $OUT/manifest_check_setup.txt 2>&1 || { echo "MANIFEST_FAIL: no call"; exit 3; }
  ( cd $PRE/collect/pre && sha256sum -c ../../SHA256SUMS_PRE_PAGES.txt ) > $OUT/pre_pages_check.txt 2>&1 || { echo "PRE_PAGES_FAIL: no call"; exit 3; }
  [ "$(h $P/$MANIFEST)" = $MANIFEST_SHA ] && [ "$(h $AUTH)" = $AUTH_SHA ] && [ "$(h $PPF)" = $PPF_SHA ] \
    && [ "$(h $ELIG)" = $ELIG_SHA ] && [ "$(h $LISTL)" = $LISTL_SHA ] && [ "$(h $PRE/SHA256SUMS_PRE_PAGES.txt)" = $PRE_SUMS_SHA ] \
    || { echo "INTEGRITY_FAIL: no call"; exit 3; }
  echo "integrity OK manifest=$MANIFEST_SHA auth=$AUTH_SHA pythonpath=$PPF_SHA eligible=$ELIG_SHA list_l=$LISTL_SHA pre_sums=$PRE_SUMS_SHA"
  RUNENV="env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 PYTHONPATH=$(cat $PPF)"
  cd $S/w1frz/tree || exit 3
  $RUNENV $PY -B -m livepaper.cli prepare --eligible $ELIG --eligible-sha $ELIG_SHA --list-l $LISTL --variant B \
    --start $START --out $OUT/POOLS_RUN.json || { echo "PREPARE_FAIL: no call"; exit 5; }
  $PY -I -c "import json,sys;d=json.load(open(sys.argv[1]));sys.stdout.write('livepaper|%d|'%d['start']+'\n'.join(d['eligible']))" \
    $OUT/POOLS_RUN.json > $OUT/SEED_INPUT.txt
  echo "pools_run=$(h $OUT/POOLS_RUN.json) seed=$(h $OUT/SEED_INPUT.txt)"
  echo "gsfa_start $(date -u +%FT%TZ)"
  env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 HTTPS_PROXY="$HTTPS_PROXY" SSL_CERT_FILE=/root/.ccr/ca-bundle.crt PYTHONPATH=$(cat $PPF) \
    $PY -B -m livepaper.cli collect-gsfa --pools $OUT/POOLS_RUN.json --out $OUT/GSFA --ledger $OUT/L.json --calls $OUT/C.jsonl \
    --authorization $AUTH --endpoint https://beta.helius-rpc.com/
  G=$?; echo "gsfa_rc=$G end $(date -u +%FT%TZ)"; [ $G -ne 0 ] && { echo "GSFA_FAIL: STOP, no ordercheck, no run"; exit 6; }
  $RUNENV $PY -B -m livepaper.cli ordercheck --pools $OUT/POOLS_RUN.json --gsfa $OUT/GSFA --gtfa $PRE/collect/pre \
    --out $OUT/ORDERCHECK.json || { echo "ORDERCHECK_FAIL: STOP, no run"; exit 7; }
  (cd $OUT/GSFA && find . -type f | sort | xargs sha256sum) > $OUT/SHA256SUMS_GSFA.txt
  echo "SETUP_DONE pools_run=$(h $OUT/POOLS_RUN.json) seed=$(h $OUT/SEED_INPUT.txt) ordercheck=$(h $OUT/ORDERCHECK.json) gsfa_sums=$(h $OUT/SHA256SUMS_GSFA.txt) ledger=$(h $OUT/L.json)"
} 2>&1 | tee -a $OUT/SETUP_LOG.txt
