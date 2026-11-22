import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'rtgate' / 'gate.py').read_text()
MUT = [
 ("        if event.key in self.seen:", "        if False:", 'duplicates_pushed'),
 ("                matches = [e for e in pending if _before(e) == _after(self.last)]", "                matches = pending[:1]", 'no_chain_ordering'),
 ("                heads = [e for e in pending if _before(e) == (0, 0)]", "                heads = pending[:1]", 'mid_curve_start_accepted'),
 ("        if self.delivered_slot is not None and event.slot <= self.delivered_slot:", "        if False:", 'late_after_flush_accepted'),
 ("        if self.slot is not None and event.slot < self.slot:", "        if False:", 'late_in_buffer_accepted'),
 ("        if self.slot is not None and event.slot > self.slot:\n            self._flush()", "        if False:\n            self._flush()", 'slot_never_flushed_before_close'),
 ("        if event.pool != self.pool:", "        if False:", 'other_pool_accepted'),
 ("        if event.violations:", "        if False:", 'violations_accepted'),
 ("        if self.status == INCOMPLETE:\n            return\n        if event.key", "        if False:\n            return\n        if event.key", 'delivery_continues_after_failure'),
 ("        if self.declared_gap is not None and self.status == COMPLETE and self.closed:\n            self._fail('declared_gap_not_healed')\n        flags", "        if False:\n            self._fail('declared_gap_not_healed')\n        flags", 'declared_gap_at_end_ignored'),
 ("            flags.append('stream_gap_with_open_position')", "            pass", 'open_position_not_flagged'),
 ("        if source not in SOURCES:", "        if False:", 'any_source_accepted'),
 ("        if self.status == COMPLETE and self.closed:\n            result = asdict", "        if self.closed:\n            result = asdict", 'incomplete_result_exposed'),
 ("                    journal=list(self.trade.journal), creditable=False,", "                    journal=list(self.trade.journal), creditable=True,", 'creditable'),
 ("    if found != PAPERSTREAM_ENGINE_SHA256:", "    if False:", 'engine_sha_unchecked'),
 ("        if self.closed:\n            raise GateError('delivery_after_close')", "        if False:\n            raise GateError('delivery_after_close')", 'delivery_after_close_accepted'),
 ("        if key in self.pushed:", "        if False:", 'rollback_of_pushed_ignored'),
 ("        if len(self.buffer) == before:", "        if False:", 'unknown_rollback_ignored'),
 ("        self.buffer = [e for e in self.buffer if e.key != key]", "        self.buffer = list(self.buffer)", 'retract_does_not_remove'),
 ("        self.pushed.add(event.key)", "        pass", 'pushed_not_recorded'),
 ("                self.work += len(pending)\n                matches", "                matches", 'work_not_counted'),
 ("        elif type(item) is tuple and item and item[0] == 'retract':\n            gate.retract(item[1])", "        elif type(item) is tuple and item and item[0] == 'retract':\n            pass", 'retract_marker_ignored'),
 ("            raise GateError('retract_after_close')", "            return None", 'retract_after_close_accepted'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'rtgate', work / 'rtgate')
    (work / 'rtgate' / 'gate.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'rtgate' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
