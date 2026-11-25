#!/bin/bash
# livesim: phases qualify then history, ONE execution (owner text eba73e3f in R03 session; R02 GO 11:37Z). NO poll.
# Integrity checks first; any mismatch = no call.
set -u
S=/tmp/claude-0/-home-user/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad
PKG=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_pkg
RUN=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run
DRV=$RUN/livesim_collect.py; UNI=$RUN/LIVESIM_UNIVERSE.json; LL=$RUN/TIME1R_20261124T102126Z/LIST_L.json
AUTH=$RUN/AUTORISATION_LIVESIM_GO.txt; CAP=16500
OUT=$RUN/LIVESIM_$(date -u +%Y%m%dT%H%M%SZ)
LOG=$S/pilot_run/launch_livesim_qh.log
PY=/tmp/claude-0/-home-user-rugger-bot-v1/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad/venv312/bin/python
DEPS=$(sed "s#:$S/cpmmpilot_pkg##" $S/cpmmpilot_pythonpath_016_final.txt)
h(){ sha256sum "$1" | cut -d' ' -f1; }
{
  echo "start $(date -u +%FT%TZ) out=$OUT"
  ( cd $PKG && sha256sum -c MANIFEST_cpmmpilot_v0_2_9_1.txt ) > $S/pilot_run/manifest_check_livesim.txt 2>&1; M=$?
  echo "manifest_rc=$M manifest=$(h $PKG/MANIFEST_cpmmpilot_v0_2_9_1.txt) driver=$(h $DRV) retry=$(h $RUN/activity_l2.py) universe=$(h $UNI) list_l=$(h $LL) auth=$(h $AUTH) out_exists=$([ -e $OUT ] && echo yes || echo no)"
  if [ $M -ne 0 ] || [ "$(h $PKG/MANIFEST_cpmmpilot_v0_2_9_1.txt)" != a800d81354024551c48f19b97ee85a7d800e6905505ef8090f561a95f21a8f9b ] \
     || [ "$(h $DRV)" != 69835299227e38d28cb2ace9a13d1b56506ea0f45da90808f4c4f6514b8b76f2 ] \
     || [ "$(h $RUN/activity_l2.py)" != 9b2c0487e8156609af434a19128e20f4871892bfe62755ae9a4535409fe1a952 ] \
     || [ "$(h $UNI)" != 82d3d5cd47236af12883b2cc0399c4a24aa43cc84e0729c32103a0c7cbeab2f5 ] \
     || [ "$(h $LL)" != c96353b9f3c0bdb25fd1b7c8af85cf0c4efd66e84480d7850252b85d8a7d8ff3 ] \
     || [ "$(h $AUTH)" != eba73e3f97ffc31a8a8a6efa8b896005dded0f4b1ec29e8efbe825e9190890bf ] || [ -e $OUT ]; then echo "INTEGRITY_FAIL: no call"; exit 3; fi
  TS=$(date -u +%s)
  run(){ cd $S/w1frz/tree && env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 HTTPS_PROXY="$HTTPS_PROXY" SSL_CERT_FILE=/root/.ccr/ca-bundle.crt \
     PYTHONPATH=$DEPS:$PKG $PY -B $DRV --phase $1 --pkg $PKG --universe $UNI --list-l $LL --out $OUT --t-start $TS --cap $CAP --authorization $AUTH; }
  echo "t_start=$TS"
  run qualify; echo "qualify_rc=$?"
  if grep -q '"verdict_run": "DONE"' $OUT/PASSES.jsonl && [ ! -e $OUT/STOP.json ]; then run history; echo "history_rc=$?"; else echo "qualify not DONE: history NOT run"; fi
  echo "end $(date -u +%FT%TZ)"
} 2>&1 | tee -a $LOG
