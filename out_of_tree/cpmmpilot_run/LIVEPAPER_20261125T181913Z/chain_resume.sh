#!/bin/bash
# Waits for the running livepaper segment to end, then resumes AT ONCE with the anchored launcher (04c265bd).
# R04 conditions (01:30Z): (1) never two livepaper processes: fail (no resume) if any run or another chain is alive;
# (2) resume ONLY if the last journal record is STOP planned_end_of_process; any other case: stop and report.
set -u
O=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run/LIVEPAPER_20261125T181913Z
LOCK=$O/.chain_resume.lock
exec 9>$LOCK
flock -n 9 || { echo "chain: another chain_resume holds the lock: NO resume"; exit 7; }
while pgrep -f "livepaper.cli run" > /dev/null; do sleep 1; done
sleep 1
if pgrep -f "livepaper.cli run" > /dev/null || pgrep -f "launch_livepaper_run.sh" > /dev/null; then
  echo "chain: a livepaper process is alive after the wait: NO resume"; exit 8; fi
LAST=$(tail -1 $O/J.jsonl)
case "$LAST" in
  *'"kind":"STOP"'*'"reason":"planned_end_of_process"'*) echo "chain: planned STOP seen $(date -u +%FT%TZ), resuming";;
  *) echo "chain: last record is not a planned STOP: NO resume"; exit 6;;
esac
bash $O/launch_livepaper_run.sh
echo "chain: launcher returned rc=$? $(date -u +%FT%TZ)"
