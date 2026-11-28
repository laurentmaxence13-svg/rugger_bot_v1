#!/bin/bash
# livesim: ONE poll pass (catches up every closed 2 h block). Owner text eba73e3f (R03 session); R02 GO required first.
# Integrity checks first; any mismatch = no call. Reuses the existing OUT (CONFIG frozen at the first pass).
set -u
S=/tmp/claude-0/-home-user/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad
PKG=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_pkg
RUN=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run
DRV=$RUN/livesim_collect.py; UNI=$RUN/LIVESIM_UNIVERSE.json; LL=$RUN/TIME1R_20261124T102126Z/LIST_L.json
AUTH=$RUN/AUTORISATION_LIVESIM_GO.txt; CAP=16500; TS=1795606731
OUT=$RUN/LIVESIM_20261125T113851Z
EL=$RUN/LIVESIM_ELIGIBLE032_20261125T144635Z/ELIGIBLE.json; ELSHA=184576ea0358e8b619d1cb1d107eb82a93a94e67d5d87d204a8831c2b45b34a9
LOG=$S/pilot_run/launch_livesim_poll.log
PY=/tmp/claude-0/-home-user-rugger-bot-v1/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad/venv312/bin/python
DEPS=$(sed "s#:$S/cpmmpilot_pkg##" $S/cpmmpilot_pythonpath_016_final.txt)
h(){ sha256sum "$1" | cut -d' ' -f1; }
{
  echo "start $(date -u +%FT%TZ)"
  ( cd $PKG && sha256sum -c MANIFEST_cpmmpilot_v0_2_9_1.txt ) > $S/pilot_run/manifest_check_livesim_poll.txt 2>&1; M=$?
  echo "manifest_rc=$M driver=$(h $DRV) eligible=$(h $EL) config=$(h $OUT/CONFIG.json) qualified=$(h $OUT/QUALIFIED.json)"
  if [ $M -ne 0 ] || [ "$(h $PKG/MANIFEST_cpmmpilot_v0_2_9_1.txt)" != a800d81354024551c48f19b97ee85a7d800e6905505ef8090f561a95f21a8f9b ] \
     || [ "$(h $DRV)" != 69835299227e38d28cb2ace9a13d1b56506ea0f45da90808f4c4f6514b8b76f2 ] \
     || [ "$(h $RUN/activity_l2.py)" != 9b2c0487e8156609af434a19128e20f4871892bfe62755ae9a4535409fe1a952 ] \
     || [ "$(h $UNI)" != 82d3d5cd47236af12883b2cc0399c4a24aa43cc84e0729c32103a0c7cbeab2f5 ] \
     || [ "$(h $LL)" != c96353b9f3c0bdb25fd1b7c8af85cf0c4efd66e84480d7850252b85d8a7d8ff3 ] \
     || [ "$(h $AUTH)" != eba73e3f97ffc31a8a8a6efa8b896005dded0f4b1ec29e8efbe825e9190890bf ] \
     || [ "$(h $OUT/CONFIG.json)" != 31f04ec8ae2516d4a9126635a40da9104fe7773e2bb67b1a0ae93e1f05c9887d ] \
     || [ "$(h $OUT/QUALIFIED.json)" != a0a95e6831809b8c820ea9845436419ddd48a72f138cc471821bbc6961c8fc9c ] \
     || [ "$(h $EL)" != $ELSHA ] || [ -e $OUT/STOP.json ]; then echo "INTEGRITY_FAIL_OR_STOPPED: no call"; exit 3; fi
  cd $S/w1frz/tree && env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 HTTPS_PROXY="$HTTPS_PROXY" SSL_CERT_FILE=/root/.ccr/ca-bundle.crt \
     PYTHONPATH=$DEPS:$PKG $PY -B $DRV --phase poll --pkg $PKG --universe $UNI --list-l $LL --out $OUT --t-start $TS --cap $CAP \
     --authorization $AUTH --eligible $EL --eligible-sha $ELSHA
  echo "rc=$? end $(date -u +%FT%TZ)"
} 2>&1 | tee -a $LOG
