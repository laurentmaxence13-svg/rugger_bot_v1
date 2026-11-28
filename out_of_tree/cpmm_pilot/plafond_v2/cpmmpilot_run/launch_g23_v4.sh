#!/bin/bash
# G2-3 pilot window collection v4 (cap v2, R02 plan e886578c; R01 26/11). Same checks as 70d503a0 with the new sha of the
# MANIFEST 0.2.8.2, of driver 0.2 and of the TWO texts. NOT before 06/12/2026 10:21:26Z. The ADDENDUM sha is PENDING until R02
# verified the owner's signature: while it is PENDING this launcher refuses (INTEGRITY_FAIL, no call). Paths: R03 reviews.
# Integrity checks first; any mismatch = no call. The driver itself refuses before T0 + 12 d.
set -u
S=/tmp/claude-0/-home-user/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad
PKG=/home/user/rugger_bot_v1/out_of_tree/cpmm_pilot/plafond_v2/cpmmpilot0282_pkg
V2RUN=/home/user/rugger_bot_v1/out_of_tree/cpmm_pilot/plafond_v2/cpmmpilot_run
RUNREPO=$V2RUN                                                # R03 review (1)(2): ONE checkout of the audited commit holds
                                                              # U2, base text, activity_l2 (loaded by the driver), ADD and OUT
DRV=$V2RUN/g23_collect_v0_2.py
COMPLETE=$V2RUN/g23_complete.py
U2=$RUNREPO/TIME2_20261124T102839Z/U2.json
BASE=$RUNREPO/AUTORISATION_G23.txt
ADD=$RUNREPO/AUTORISATION_G23_ADDENDUM.txt                   # created by R03 from the owner's message, after R02
ADD_SHA=e886578ca327cc418e9e8816907232dea41469e03884a7de3180bf1042793d68   # signed (GO 09e874e3, R02 verified 28/11)
SHEET=e2f8411d2b7911f05cbbf3b38657ca88d5afa85023d58ceb4b26ea6a8ba46819
VCODE=8528b66f5add2a5c950b21e2121382a87fc8db5ab543ac60d25a0588ad765789   # R02 14:31Z: MANIFEST of g23run 0.1.2, the verdict code since cda64700
OUT=$RUNREPO/G23_$(date -u +%Y%m%dT%H%M%SZ)
LOG=$S/pilot_run/launch_g23_v4.log                            # R03 review (4)
PY=/tmp/claude-0/-home-user-rugger-bot-v1/420f9b0d-d94a-50f0-ae37-b89b76d967d7/scratchpad/venv312/bin/python
DEPS=$(sed "s#:$S/cpmmpilot_pkg##" $S/cpmmpilot_pythonpath_016_final.txt)
h(){ sha256sum "$1" | cut -d' ' -f1; }
{
  echo "start $(date -u +%FT%TZ) out=$OUT"
  if [ "$(date -u +%s)" -lt 1796552486 ]; then echo "TOO_EARLY: no call"; exit 4; fi
  ( cd $PKG && sha256sum -c MANIFEST_cpmmpilot_v0_2_8_2.txt ) > $S/pilot_run/manifest_check_g23_v4.txt 2>&1; M=$?
  echo "manifest_rc=$M manifest=$(h $PKG/MANIFEST_cpmmpilot_v0_2_8_2.txt) driver=$(h $DRV) complete=$(h $COMPLETE) retry=$(h $RUNREPO/activity_l2.py) u2=$(h $U2) base=$(h $BASE) addendum=$([ -e $ADD ] && h $ADD || echo missing) out_exists=$([ -e $OUT ] && echo yes || echo no)"
  if [ "$ADD_SHA" = PENDING ] || [ ! -e $ADD ] || [ $M -ne 0 ] || [ "$(h $PKG/MANIFEST_cpmmpilot_v0_2_8_2.txt)" != 41caceb1460ff1a12fee7195ad5ab838d439b7bff2f47c277500d781a94b8f6d ] \
     || [ "$(h $DRV)" != e21239d0ab9303d5278a90547814dfccecd885dae1e820f62c4fa99487e46c8e ] || [ "$(h $COMPLETE)" != f66c8e32e1f42bb4b1ed8b184e1b6e07ec536f8254c00772fac2bf82024957a5 ] \
     || [ "$(h $RUNREPO/activity_l2.py)" != 9b2c0487e8156609af434a19128e20f4871892bfe62755ae9a4535409fe1a952 ] \
     || [ "$(h $U2)" != 3ca0260aa187f8df99ab422fc74fbbb1da4404d6f6b175548270ade3e731a963 ] \
     || [ "$(h $BASE)" != 3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b ] || [ "$(h $ADD)" != "$ADD_SHA" ] \
     || [ "$ADD_SHA" = 3d6999ecdb19d9e23b34810e208c507e85ec1ef5baca189a58924eb04ea4d66b ] || [ -e $OUT ]; then echo "INTEGRITY_FAIL: no call"; exit 3; fi
  CX=$S/cpmmdeps/out_of_tree/cpmmx_pkg; CC=$S/cpmmdeps/out_of_tree/cpmm_pilot/cpmmcost_pkg
  echo "deps: pythonpath=$(h $S/cpmmpilot_pythonpath_016_final.txt) cpmmcost_v0_3=$(h $CC/MANIFEST_cpmmcost_v0_3.txt) cpmmcost_check_bad=$( (cd $CC && sha256sum -c MANIFEST_cpmmcost_v0_3.txt 2>&1) | grep -vc ': OK$') cpmmx_tree=$( (cd $CX && find cpmmx -name '*.py' -print0 | sort -z | xargs -0 sha256sum) | sha256sum | cut -d' ' -f1) (no cpmmx MANIFEST exists)"
  PP=$(h $S/cpmmpilot_pythonpath_016_final.txt); CCM=$(h $CC/MANIFEST_cpmmcost_v0_3.txt)
  CCB=$( (cd $CC && sha256sum -c MANIFEST_cpmmcost_v0_3.txt 2>&1) | grep -vc ': OK$')
  CXT=$( (cd $CX && find cpmmx -name '*.py' -print0 | sort -z | xargs -0 sha256sum) | sha256sum | cut -d' ' -f1)
  if [ "$PP" != 3cfa5e0dca3a0c2cc53683d02e94d02a2b709965b2f37fafa17f5d884d237d22 ] \
     || [ "$CCM" != a0bd2adbfaeaa5b14b79c200b066f9a14bb1408c57469e319d6e1db9b92de547 ] || [ "$CCB" != 0 ] \
     || [ "$CXT" != 9e64445e764a592841457b790f31f2c74bc9dcc28d0d1c65c661856111ed6205 ]; then echo "INTEGRITY_FAIL (deps): no call"; exit 3; fi
  cd $S/w1frz/tree && env -i PATH=/usr/bin:/bin RUGGER_NO_DOTENV=1 HTTPS_PROXY="$HTTPS_PROXY" SSL_CERT_FILE=/root/.ccr/ca-bundle.crt \
     PYTHONPATH=$DEPS:$PKG $PY -B $DRV --pkg $PKG --u2 $U2 --out $OUT --sheet-sha $SHEET --verdict-code-sha $VCODE --authorization $ADD --base-text $BASE
  echo "rc=$? end $(date -u +%FT%TZ)"
  env -i PATH=/usr/bin:/bin PYTHONPATH=$DEPS:$PKG $PY -B $COMPLETE $OUT          # R03 review (3); informative only; « no verdict on a partial » stays with R02
} 2>&1 | tee -a $LOG
