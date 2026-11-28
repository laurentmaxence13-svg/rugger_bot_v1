#!/bin/bash
# livesim identity (F3), ONE offline run, 0 credit (unshare -rn). R02 GO 10:40Z.
set -u
S=/tmp/claude-0/-home-user/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad; R=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run/STEP1A2R_20261124T164909Z; RUN=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run
PY=/tmp/claude-0/-home-user-rugger-bot-v1/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad/venv312/bin/python
W=$S/identity_layout; rm -rf $W; mkdir -p $W/collect; ln -s $R/pre_pages $W/collect/pre
OUT=$RUN/LIVESIM_IDENTITY_$(date -u +%Y%m%dT%H%M%SZ); mkdir $OUT
( cd $R/pre_pages && sha256sum -c ../SHA256SUMS_PRE_PAGES.txt | grep -vc ': OK$' ) > $OUT/pre_pages_bad.txt
echo "pre_pages_bad=$(cat $OUT/pre_pages_bad.txt) n1rot_result=$(sha256sum $RUN/N1ROT_20261124T215521Z/N1ROT_RESULT.json|cut -c1-64) u2=$(sha256sum $RUN/TIME2_20261124T102839Z/U2.json|cut -c1-64)" | tee $OUT/RUN_INFO.txt
cd $S/w1frz/tree && unshare -rn env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 PYTHONPATH=$(cat $S/livesim_identity_pythonpath.txt) $PY -B -m livesim.sim identity --a2r $W --u2 $RUN/TIME2_20261124T102839Z/U2.json --result $RUN/N1ROT_20261124T215521Z/N1ROT_RESULT.json --t0-time 1795515686 --t0-slot 473309024 --out $OUT/IDENTITY.json 2>&1 | tee -a $OUT/RUN_INFO.txt
echo "rc=${PIPESTATUS[0]} out=$OUT"
