#!/bin/bash
# Waits for the running livepaper segment to end (planned STOP), then resumes AT ONCE with the anchored launcher.
# Started a few minutes before the planned end so that wait + 110 min stays under the 2 h process limit.
set -u
O=/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run/LIVEPAPER_20261125T181913Z
while pgrep -f "livepaper.cli run" > /dev/null; do sleep 1; done
LAST=$(tail -1 $O/J.jsonl)
case "$LAST" in
  *'"kind":"STOP"'*'"reason":"planned_end_of_process"'*) echo "chain: planned stop seen $(date -u +%FT%TZ), resuming";;
  *) echo "chain: last record is not a planned STOP: NO resume"; exit 6;;
esac
exec bash $O/launch_livepaper_run.sh
