import json, shutil, subprocess, sys
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
src = (D / 'paperstream' / 'engine.py').read_text()
MUT = [
 ("            if event.slot > self.limit:", "            if event.slot >= self.limit:", 'landing_one_slot_early'),
 ("        self.rate, self.amount, self.limit, self.phase = rate, amount, events[k].slot + model.latency_slots, 'landing'", "        self.rate, self.amount, self.limit, self.phase = rate, amount, events[k].slot, 'landing'", 'latency_ignored'),
 ("        if self.pending_exit_slot is not None and events[j].slot > self.pending_exit_slot:", "        if self.pending_exit_slot is not None:", 'sell_before_exit_latency'),
 ("        if landing is not None and events[j].block_time > landing:", "        if landing is not None and events[j].block_time >= landing:", 'clock_exit_early'),
 ("            self.state = R._replay_real(self.state, events[j])", "            pass", 'holding_ignores_real_trades'),
 ("                self.pending_exit_slot = events[j].slot + self.model.latency_slots", "                self.pending_exit_slot = events[j].slot", 'exit_latency_ignored'),
 ("        result.tx_costs += self.model.tx_cost\n        result.hold_slots = self.events[exit_index].slot - self.position.entry_slot", "        result.hold_slots = self.events[exit_index].slot - self.position.entry_slot", 'sale_tx_cost_dropped'),
 ("            if event.slot < last.slot or event.block_time < last.block_time:", "            if False:", 'time_order_unchecked'),
 ("        if self.done:\n            raise StreamError('event_after_the_end')", "        if False:\n            raise StreamError('event_after_the_end')", 'push_after_end_allowed'),
 ("    hrr.replay = stream_replay\n    try:", "    try:", 'streaming_not_swapped_in'),
 ("        hrr.replay = original", "        pass", 'frozen_engine_not_restored'),
 ("        if residual != 0:", "        if False:", 'reconcile_unchecked'),
 ("    if hashlib.sha256(raw).hexdigest() != a.reference_sha256:", "    if False:", 'reference_sha_ignored'),
 ("    return dict(min_qualified_cycles=POLICY['min_qualified_cycles'], min_creator_groups=POLICY['min_creator_groups'],", "    return dict(min_qualified_cycles=10, min_creator_groups=POLICY['min_creator_groups'],", 'threshold_lowered'),
 ("CATEGORY = 'HISTORICAL_REPLAY'", "CATEGORY = 'GENUINE_MASTER_PAPER'", 'label_genuine'),
 ("    if _sha_file(path) != sha256:", "    if False:", 'series_sha_unchecked'),
 ("    if series.label != 'COLLECTED' or series.max_age_ms == sus.MAX_AGE_MS and series.max_confidence_ppm is None:", "    if False:", 'series_guard_dropped'),
 ("    if path is None or sha256 is None:\n        raise StreamError('sol_usd_series_required')", "    if False:\n        raise StreamError('sol_usd_series_required')", 'series_optional'),
 ("            bundle = l1_bundle(pools_dir, series)", "            bundle = l1_bundle(pools_dir, None if streaming else series)", 'series_not_passed_to_the_stream'),
 ("                          placebo_arm=True)\n\n\ndef records", "                          placebo_arm=False)\n\n\ndef records", 'placebo_arm_dropped'),
 ("hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(pools_dir)[2]], 'manifest'),", "None,", 'creator_history_dropped'),
 ("    if params.sol_usd is not None:\n        raise StreamError('declared_sol_usd_rate_refused')", "    if False:\n        raise StreamError('declared_sol_usd_rate_refused')", 'declared_rate_accepted'),
 ("        del JOURNALS[start:]\n", "", 'journal_kept_in_memory'),
 ("    if _sha_file(Path(pools_dir) / 'MANIFEST.json') != manifest_sha256:", "    if False:", 'manifest_unchecked'),
 ("    ok = doc['identical_to_reference'] and reconciled == closed and doc.get('matches_expected_bundle', True)", "    ok = doc['identical_to_reference'] and reconciled == closed", 'expected_bundle_ignored'),
 ("    keep = ('decisions', 'enter_decisions', 'entries', 'outcomes', 'closed_cycles', 'blocking_reasons')", "    keep = ('decisions', 'enter_decisions', 'entries', 'outcomes', 'closed_cycles', 'blocking_reasons', 'pnl_lamports')", 'pnl_in_counts'),
 ("    hrr.replay_pool = _journaled_replay_pool(original, journal_dir)\n    try:\n        yield\n    finally:\n        hrr.replay_pool = original", "    hrr.replay_pool = _journaled_replay_pool(original, journal_dir)\n    try:\n        yield\n    finally:\n        pass", 'replay_pool_not_restored'),
]
out = []
for old, new, name in MUT:
    assert src.count(old) == 1, name
    work = M / name
    shutil.copytree(D / 'paperstream', work / 'paperstream')
    (work / 'paperstream' / 'engine.py').write_text(src.replace(old, new))
    r = subprocess.run([V, '-B', '-m', 'pytest', str(work / 'paperstream' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                       cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
    out.append(dict(mutant=name, detected=r.returncode != 0))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
