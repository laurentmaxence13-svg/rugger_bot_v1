#!/bin/bash
# livepaper RUN (R02 GO 18:24Z; owner 1366025b + confirmation acef3010). First start or resume (same command).
set -u
S=/tmp/claude-0/-home-user/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad; OUT=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run/LIVEPAPER_20261125T181913Z; RUN=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run
P=$S/livepaper_1a626c8/out_of_tree/cpmm_pilot/livepaper012_pkg
AUTH=$RUN/AUTORISATION_LIVEPAPER.txt
PY=/tmp/claude-0/-home-user-rugger-bot-v1/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad/venv312/bin/python
START=1795632000; END=1795718400
h(){ sha256sum "$1" | cut -d' ' -f1; }
{
  echo "launcher 2026-11-25T18:25:09Z"
  ( cd $P && sha256sum -c MANIFEST_livepaper_v0_1_2.txt ) > $OUT/manifest_check_run.txt 2>&1; M=$?
  if [ $M -ne 0 ] || [ "$(h $P/MANIFEST_livepaper_v0_1_2.txt)" != 941b1782d9a4216111583e9df40bf3372c72b3cfd7ebec98ac3c597925815aa0 ] \
     || [ "$(h $AUTH)" != 1366025b6290c0a748c2190eebc5e3ee078a25868ef005591710b23658ebface ] \
     || [ "$(h $OUT/POOLS_RUN.json)" != 683da83626b201fa91bfcf38f220b6b5601dee18648bcf67afff9d6b4801a9f0 ] \
     || [ "$(h $OUT/ORDERCHECK.json)" != 815b94fd160420c111ea2e3fd881dad823cfa46a7014c052cd517b977908753c ] \
     || [ ! -e $OUT/L.json ] || [ -e $OUT/STOP_R03.txt ]; then echo "INTEGRITY_FAIL_OR_STOPPED: no call"; exit 3; fi
  if [ ! -e $OUT/J.jsonl ]; then
    while [ $(date -u +%s) -lt $START ]; do sleep 1; done
    if [ $(date -u +%s) -gt $((START+60)) ]; then echo "LATE_FIRST_START: no call (needs new POOLS_RUN + seed)"; exit 4; fi
  fi
  if [ $(date -u +%s) -ge $END ]; then echo "PAST_24H: no call"; exit 5; fi
  echo "run_start $(date -u +%FT%TZ) $(date -u +%s) resume=$([ -e $OUT/J.jsonl ] && echo yes || echo no)"
  cd $S/w1frz/tree && env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 HTTPS_PROXY="$HTTPS_PROXY" SSL_CERT_FILE=/root/.ccr/ca-bundle.crt \
    PYTHONPATH=$(cat $S/livepaper_pythonpath.txt) $PY -B -m livepaper.cli run --pools $OUT/POOLS_RUN.json --ordercheck $OUT/ORDERCHECK.json \
    --ordercheck-sha 815b94fd160420c111ea2e3fd881dad823cfa46a7014c052cd517b977908753c --journal $OUT/J.jsonl --store $OUT/PAGES \
    --seed-sha acc592961e19a8acd31e30699585db669dd7f7baceb930f9778b6a4c9370f00c --ledger $OUT/L.json --calls $OUT/C.jsonl \
    --authorization $AUTH --endpoint https://beta.helius-rpc.com/ --max-minutes 110
  echo "rc=$? end $(date -u +%FT%TZ)"
} 2>&1 | tee -a $OUT/RUN_LOG.txt
