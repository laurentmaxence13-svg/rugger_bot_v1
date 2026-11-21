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
 ("        if len(found) != 1 or residual(row, found[0]):", "        if len(found) != 1:", 'reconcile_unchecked'),
 ("    if hashlib.sha256(raw).hexdigest() != a.reference_sha256:", "    if False:", 'reference_sha_ignored'),
 ("    return dict(min_qualified_cycles=POLICY['min_qualified_cycles'], min_creator_groups=POLICY['min_creator_groups'],", "    return dict(min_qualified_cycles=10, min_creator_groups=POLICY['min_creator_groups'],", 'threshold_lowered'),
 ("CATEGORY = 'HISTORICAL_REPLAY'", "CATEGORY = 'GENUINE_MASTER_PAPER'", 'label_genuine'),
 ("    if _sha_file(path) != sha256:", "    if False:", 'series_sha_unchecked'),
 ("    if series.label != 'COLLECTED' or series.max_age_ms == sus.MAX_AGE_MS and series.max_confidence_ppm is None:", "    if False:", 'series_guard_dropped'),
 ("    if path is None or sha256 is None:\n        raise StreamError('sol_usd_series_required')", "    if False:\n        raise StreamError('sol_usd_series_required')", 'series_optional'),
 ("            bundle = l1_bundle(pools_dir, series)", "            bundle = l1_bundle(pools_dir, None if streaming else series)", 'series_not_passed_to_the_stream'),
 ("hrr.CreatorHistory.from_archives([a for _e, a in hrr.load_fixtures(pools_dir)[2]], 'manifest'),", "None,", 'creator_history_dropped'),
 ("    if params.sol_usd is not None:\n        raise StreamError('declared_sol_usd_rate_refused')", "    if False:\n        raise StreamError('declared_sol_usd_rate_refused')", 'declared_rate_accepted'),
 ("        del JOURNALS[start:]\n        if checkpoint is not None:\n            checkpoint.put(pool, record", "        if checkpoint is not None:\n            checkpoint.put(pool, record", 'journal_kept_in_memory'),
 ("    if _sha_file(Path(pools_dir) / 'MANIFEST.json') != manifest_sha256:", "    if False:", 'manifest_unchecked'),
 ("        ok = ok and doc['matches_expected_bundle_file']\n", "", 'expected_bundle_file_ignored'),
 ("        ok = ok and doc['matches_expected_bundle_json']\n", "", 'expected_bundle_json_ignored'),
 ("    keep = ('decisions', 'enter_decisions', 'entries', 'outcomes', 'closed_cycles', 'blocking_reasons')", "    keep = ('decisions', 'enter_decisions', 'entries', 'outcomes', 'closed_cycles', 'blocking_reasons', 'pnl_lamports')", 'pnl_in_counts'),
 ("    hrr.replay_pool = _journaled_replay_pool(original, journal_dir, checkpoint)\n    try:\n        yield\n    finally:\n        hrr.replay_pool = original", "    hrr.replay_pool = _journaled_replay_pool(original, journal_dir, checkpoint)\n    try:\n        yield\n    finally:\n        pass", 'replay_pool_not_restored'),
 ("        if doc.get('key') != self.key(pool):", "        if False:", 'checkpoint_key_unchecked'),
 ("        if _sha_file(entry) != sha.read_text(encoding='utf-8').strip():", "        if False:", 'checkpoint_sha_unchecked'),
 ("        self.context = dict(context, mode='stream')", "        self.context = dict(context)", 'checkpoint_mode_not_in_key'),
 ("    if checkpoint_dir is not None and not streaming:\n        raise StreamError('checkpoint_is_for_the_streaming_run_only')", "    if False:\n        raise StreamError('checkpoint_is_for_the_streaming_run_only')", 'checkpoint_in_batch_allowed'),
 ("                  tx_costs=buy['tx_cost'] + sell['tx_cost'] - row['tx_costs'])", "                  tx_costs=0)", 'residual_tx_costs_dropped'),
 ("    checks = dict(pnl=sell['received'] - buy['spent'] - (buy['tx_cost'] + sell['tx_cost']) - row['failed_attempt_costs']", "    checks = dict(pnl=sell['received'] - buy['spent'] - (buy['tx_cost'] + sell['tx_cost'])", 'residual_failed_costs_dropped'),
 ("        if a.reference is None and a.expect_bundle_file_sha256 is None:\n            raise StreamError('nothing_to_compare_with')", "        if False:\n            raise StreamError('nothing_to_compare_with')", 'run_without_comparison'),
 ("                write(pool, doc['journals'])\n", "", 'reused_entry_journals_dropped'),
 ("                  placebo_arm=True)\n\n\ndef checkpoint_context", "                  placebo_arm=False)\n\n\ndef checkpoint_context", 'placebo_arm_dropped_03'),

 ("        memory = dayj.memory_guard('trials', a.pools, a.memory_override)", "        memory = dayj.memory_guard('trials', a.pools, True)", 'memory_guard_bypassed'),
 ("    ok = reconciled == closed and doc['bundle_sha256_consistent']", "    ok = reconciled == closed", 'bundle_sha_consistency_ignored'),
 ("    return hashlib.sha256(_canonical_strict(bundle).encode()).hexdigest()", "    return hashlib.sha256(_canonical(bundle).encode()).hexdigest()", 'json_sha_lax_serialization'),
 ("        return w1_run._write_json(Path(tmp) / 'bundles' / 'L1.json.gz', bundle)", "        return w1_run._write_json(Path(tmp) / 'bundles' / 'L1.json', bundle)", 'file_sha_without_gzip'),
 ("        if (a.expect_bundle_file_sha256 is None) != (a.expect_bundle_json_sha256 is None):", "        if False:", 'file_and_json_not_paired'),
 ("                                         and doc['bundle_json_sha256'] == reference['bundle_json_sha256'])", ")", 'reference_json_sha_ignored'),
 ("        ok = ok and doc['matches_expected_bundle_field']\n", "", 'expected_bundle_field_ignored'),
 ("        if a.expect_bundle_field_sha256 is not None and a.expect_bundle_file_sha256 is None:", "        if False:", 'field_sha_as_substitute'),
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
