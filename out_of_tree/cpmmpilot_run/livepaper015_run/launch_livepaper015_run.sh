#!/bin/bash
# FILLED 28/11 (NOT frozen, NOT armed): livepaper 0.1.5 run/resume launcher. Fill the @@...@@ values ONLY after the owner's
# signed text is in the R03 session and R02 anchored it; then R02 audits this file before any use.
# R02 03:08Z: NEW folder, NEW POOLS/seed/GSFA/ORDERCHECK/ledger/calls; never continues the 0.1.2 journal (D15).
set -u
S=/tmp/claude-0/-home-user/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad
OUT=@@OUT_DIR@@                       # new folder, e.g. .../cpmmpilot_run/LIVEPAPER015_<ts>
P=/tmp/claude-0/-home-user/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad/livepaper_9800986/out_of_tree/cpmm_pilot/livepaper015_pkg   # git archive of 9800986
MANIFEST=MANIFEST_livepaper_v0_1_5.txt; MANIFEST_SHA=9ac7089c8ee97ec49cf67896c666fa0ec57b248c619c0ecb38f11a0557c649f9
AUTH=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run/AUTORISATION_LIVEPAPER_V7.txt; AUTH_SHA=31dfed474aa18a6e463bae0bf1e16d465a8edc0da8ad15362d1019f51ba66050          # owner's signed text (v7, GO 09e874e3), byte-exact
POOLS_SHA=@@POOLS_RUN_SHA@@; SEED=@@SEED_SHA@@; OC_SHA=@@ORDERCHECK_SHA@@
START=@@START@@; END=$((START+86400))
PPF=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run/livepaper015_run/PYTHONPATH_015.txt; PPF_SHA=488b87735e688bd02e15da2d8d22af7398c554d6a6701d2ecde6902f9eda0a28
PY=/tmp/claude-0/-home-user-rugger-bot-v1/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad/venv312/bin/python
h(){ sha256sum "$1" | cut -d' ' -f1; }
{
  echo "launcher $(date -u +%FT%TZ)"
  [ -e $OUT/STOP_R03_v015.txt ] && { echo "STOP_R03_v015 present: no call"; exit 3; }
  ( cd $P && sha256sum -c $MANIFEST ) > $OUT/manifest_check_run.txt 2>&1 || { echo "MANIFEST_FAIL: no call"; exit 3; }
  [ "$(h $P/$MANIFEST)" = "$MANIFEST_SHA" ] && [ "$(h $AUTH)" = "$AUTH_SHA" ] && [ "$(h $OUT/POOLS_RUN.json)" = "$POOLS_SHA" ] \
    && [ "$(h $OUT/ORDERCHECK.json)" = "$OC_SHA" ] && [ "$(h $PPF)" = "$PPF_SHA" ] && [ "$(h $OUT/SEED_INPUT.txt)" = "$SEED" ] && [ -e $OUT/L.json ] || { echo "INTEGRITY_FAIL: no call"; exit 3; }
  if [ ! -e $OUT/J.jsonl ]; then
    while [ $(date -u +%s) -lt $START ]; do sleep 1; done
    [ $(date -u +%s) -gt $((START+60)) ] && { echo "LATE_FIRST_START: no call"; exit 4; }
  fi
  [ $(date -u +%s) -ge $END ] && { echo "PAST_24H: no call"; exit 5; }
  echo "run_start $(date -u +%FT%TZ) $(date -u +%s) resume=$([ -e $OUT/J.jsonl ] && echo yes || echo no)"
  cd $S/w1frz/tree && env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 HTTPS_PROXY="$HTTPS_PROXY" SSL_CERT_FILE=/root/.ccr/ca-bundle.crt \
    PYTHONPATH=$(cat $PPF) $PY -B -m livepaper.cli run --pools $OUT/POOLS_RUN.json --ordercheck $OUT/ORDERCHECK.json \
    --ordercheck-sha $OC_SHA --journal $OUT/J.jsonl --store $OUT/PAGES --seed-sha $SEED --ledger $OUT/L.json --calls $OUT/C.jsonl \
    --authorization $AUTH --endpoint https://beta.helius-rpc.com/ --max-minutes 110
  echo "rc=$? end $(date -u +%FT%TZ)"
} 2>&1 | tee -a $OUT/RUN_LOG.txt
