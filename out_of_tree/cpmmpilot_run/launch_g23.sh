#!/bin/bash
# G2-3 pilot window collection, ONE run (owner text 3d6999ec, R02 conditional GO 08838b59). NOT before 06/12/2026 10:21:26Z.
# Integrity checks first; any mismatch = no call. The driver itself refuses before T0 + 12 d.
set -u
S=/tmp/claude-0/-home-user/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad
PKG=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_pkg
RUNREPO=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run
DRV=$RUNREPO/g23_collect.py
U2=$RUNREPO/TIME2_20261124T102839Z/U2.json
AUTH=$RUNREPO/AUTORISATION_G23.txt
SHEET=e2f8411d2b7911f05cbbf3b38657ca88d5afa85023d58ceb4b26ea6a8ba46819
VCODE=3e3cb1053b0b7a792e480460e53b14f771e1d9fdd13be81e17daf02b4054747a
OUT=$RUNREPO/G23_$(date -u +%Y%m%dT%H%M%SZ)
LOG=$S/pilot_run/launch_g23.log
PY=/tmp/claude-0/-home-user-rugger-bot-v1/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad/venv312/bin/python
DEPS=$(sed "s#:$S/cpmmpilot_pkg##" $S/cpmmpilot_pythonpath_016_final.txt)
h(){ sha256sum "$1" | cut -d' ' -f1; }
{
  echo "start $(date -u +%FT%TZ) out=$OUT"
  if [ "$(date -u +%s)" -lt 1796552486 ]; then echo "TOO_EARLY: no call"; exit 4; fi
  ( cd $PKG && sha256sum -c MANIFEST_cpmmpilot_v0_2_8_1.txt ) > $S/pilot_run/manifest_check_g23.txt 2>&1; M=$?
  echo "manifest_rc=$M manifest=$(h $PKG/MANIFEST_cpmmpilot_v0_2_8_1.txt) driver=$(h $DRV) retry=$(h $RUNREPO/activity_l2.py) u2=$(h $U2) auth=$(h $AUTH) out_exists=$([ -e $OUT ] && echo yes || echo no)"
  if [ $M -ne 0 ] || [ "$(h $PKG/MANIFEST_cpmmpilot_v0_2_8_1.txt)" != ba38eba3bdbebfb670abbcd6e55a68ee476128fd2d4a0ef49120780d3082a172 ] \
     || [ "$(h $DRV)" != bf62d082cf24f88dee2e80b4277054c63380ddf7995bc34dfe913c48cb66ccad ] \
     || [ "$(h $RUNREPO/activity_l2.py)" != 9b2c0487e8156609af434a19128e20f4871892bfe62755ae9a4535409fe1a952 ] \
     || [ "$(h $U2)" != 3ca0260aa187f8df99ab422fc74fbbb1da4404d6f6b175548270ade3e731a963 ] \
     || [ "$(h $AUTH)" != 3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b ] || [ -e $OUT ]; then echo "INTEGRITY_FAIL: no call"; exit 3; fi
  cd $S/w1frz/tree && env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 HTTPS_PROXY="$HTTPS_PROXY" SSL_CERT_FILE=/root/.ccr/ca-bundle.crt \
     PYTHONPATH=$DEPS:$PKG $PY -B $DRV --pkg $PKG --u2 $U2 --out $OUT --sheet-sha $SHEET --verdict-code-sha $VCODE --authorization $AUTH
  echo "rc=$? end $(date -u +%FT%TZ)"
} 2>&1 | tee -a $LOG
