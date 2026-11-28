import json, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
D, V, W, M, PP = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]), sys.argv[5]
MUT = [
 # fill.py: the live anchor
 ('fill.py', "    ai = anchor_index(line, anchor)\n    land = anchor.slot + latency_slots * (1 + buy_failures)", "    ai = anchor_index(line, anchor)\n    land = anchor.slot + latency_slots", 'exit_land_ignores_buy_failures'),
 ('fill.py', "    deadline = anchor.time + R.CLOCK_S\n", "    deadline = anchor.time + R.CLOCK_S + 1\n", 'clock_deadline_shifted'),
 ('fill.py', "        if ratio >= R.TP or ratio <= R.SL:", "        if ratio > R.TP or ratio <= R.SL:", 'tp_strict'),
 ('fill.py', "    land = anchor.slot + latency_slots * (1 + failures.buy)\n    states", "    land = known.slot + latency_slots * (1 + failures.buy)\n    states", 'buy_lands_after_the_trigger'),
 ('fill.py', "        decision_state = TL.after_swap(known, fees.protocol_fee_rate, fees.fund_fee_rate)", "        decision_state = TL.after_swap(line.swaps[0], fees.protocol_fee_rate, fees.fund_fee_rate)", 'guard_on_another_state'),
 ('fill.py', "        if type(exit_time) is not int or exit_time <= anchor.time:", "        if type(exit_time) is not int or exit_time < anchor.time:", 'exit_time_check_loose'),
 ('fill.py', "    net = received - CC.STAKE_LAMPORTS - tx_buy - tx_sell - wsol_close - cleanup - rent_lost", "    net = received - CC.STAKE_LAMPORTS - tx_buy - tx_sell - cleanup - rent_lost", 'net_without_wsol_close'),
 ('fill.py', "                  receipt_time=anchor.time, guard_ppm", "                  receipt_time=anchor.slot, guard_ppm", 'receipt_time_wrong'),
 ('fill.py', "    sold, sell_state, kind, limit = min(candidates, key=lambda row: row[0].output_amount)", "    sold, sell_state, kind, limit = max(candidates, key=lambda row: row[0].output_amount)", 'best_sale_state'),
 ('fill.py', "        if s.key == tuple(anchor.key):\n            return i", "        if s.key == tuple(anchor.key):\n            return min(i + 1, len(line.swaps) - 1)", 'anchor_index_off'),
 ('fill.py', "    bought, buy_state = min(buys, key=lambda pair: pair[0].output_amount)", "    bought, buy_state = max(buys, key=lambda pair: pair[0].output_amount)", 'best_buy_state'),
 # journal.py
 ('journal.py', "seq=len(self.records) + len(self.pending), prev=self.head)", "seq=len(self.records) + len(self.pending), prev=ZERO)", 'chain_not_linked'),
 ('journal.py', "or r.get('kind') not in KINDS or r.get('sha') != _sha(r):", "or r.get('kind') not in KINDS:", 'sha_not_verified'),
 ('journal.py', "VOLATILE = ('wall', 'mono_ns', 'processing_ms', 'fetch_ms')", "VOLATILE = ('mono_ns', 'processing_ms', 'fetch_ms')", 'wall_not_volatile'),
 ('journal.py', "RUNNER_KINDS = ('CATCHUP', 'ERROR', 'STOP')", "RUNNER_KINDS = ('CATCHUP', 'ERROR')", 'stop_not_skipped'),
 ('journal.py', "        if self.records and not replay:\n            raise", "        if False:\n            raise", 'existing_journal_appended'),
 ('journal.py', "            if stable(existing) != stable(json.loads(canonical(candidate))):", "            if False:", 'replay_not_compared'),
 # engine.py
 ('engine.py', "SETTLE_SLOTS, SETTLE_S = 150, 60", "SETTLE_SLOTS, SETTLE_S = 0, 0", 'nothing_settled'),
 ('engine.py', "            if not ok:\n                continue", "            if False:\n                continue", 'decisions_without_eligibility'),
 ('engine.py', "                if s.block_time < self.start or s.signature in self.decided[pool]:", "                if s.signature in self.decided[pool]:", 'pre_start_decided'),
 ('engine.py', "                self.decided[pool].add(s.signature)\n", "", 'decided_twice'),
 ('engine.py', "        anchor = F.Anchor(tuple(known.swaps[-1].key), receipt_slot, receipt_time)", "        anchor = F.Anchor(tuple(known.swaps[0].key), receipt_slot, receipt_time)", 'anchor_on_the_first_swap'),
 ('engine.py', "    return PLACEBO_MIN_S + int(hashlib.sha256(('%s|%s|%s' % (seed_sha, pool, signature)).encode()).hexdigest()[:8],", "    return PLACEBO_MIN_S + int(hashlib.sha256(('%s|%s' % (pool, signature)).encode()).hexdigest()[:8],", 'placebo_seed_ignored'),
 ('engine.py', "            if self.g0[pool]['admitted'] and row['b3'] > 0 and known[pool].swaps:", "            if known[pool].swaps:", 'placebo_without_eligibility'),
 ('engine.py', "                          decided_after_gap=gap is not None and trigger.block_time < gap[1])", "                          decided_after_gap=False)", 'gap_backlog_not_flagged'),
 ('engine.py', "            if exit_slot is not None and exit_slot > settled_slot:\n                return", "            if False:\n                return", 'exit_slot_not_settled'),
 ('engine.py', "            if exit_time is not None and exit_time > settled_time:\n                return", "            if False:\n                return", 'exit_time_not_settled'),
 ('engine.py', "        if land > settled_slot:\n            return", "        if land > settled_slot + 150:\n            return", 'landing_not_settled'),
 ('engine.py', "                if raw is None or raw_sha(raw) != x['raw_sha256']:", "                if raw is None:", 'stored_sha_not_checked'),
 ('engine.py', "    journal.skip_runner_records()\n    if journal.replaying:\n        raise", "    journal.skip_runner_records()\n    if False:\n        raise", 'trailing_records_accepted'),
 ('engine.py', "        if self.variant == 'B':\n            line, _rep = rebuilt(", "        if False:\n            line, _rep = rebuilt(", 'variant_b_not_rebuilt'),
 ('engine.py', "            if gate != self.g0[pool]:", "            if True:", 'g0_every_step'),
 ('engine.py', "                if type(raw.get('slot')) is not int or raw['slot'] > receipt_slot:", "                if type(raw.get('slot')) is not int:", 'future_transaction_accepted'),
 ('engine.py', "                          trigger_received_step=self.first_step[pool].get(trigger.signature),", "                          trigger_received_step=n,", 'received_step_not_recorded'),
 ('engine.py', "                     store=tmp_path", "                     store=tmp_path", 'noop_placeholder') if False else ('engine.py', "        LS.check_universe(names)", "        pass", 'pilot_pools_accepted'),
 # source.py
 ('source.py', "CEILING, HARD_STOP = 25_000, 24_500", "CEILING, HARD_STOP = 25_000, 25_000", 'hard_stop_25000'),
 ('source.py', "        if self.credits + cost > self.hard_stop:", "        if self.credits + cost > self.hard_stop + 10:", 'hard_stop_overrun'),
 ('source.py', "MODE_POLL = {'gsfa_rank': 30, 'gtfa': 150}", "MODE_POLL = {'gsfa_rank': 30, 'gtfa': 30}", 'gtfa_polled_every_30_s'),
 ('source.py', "VERDICT_MODE = {'a-ok': 'gsfa_rank', 'b': 'gtfa'}", "VERDICT_MODE = {'a-ok': 'gsfa_rank', 'b': 'gsfa_rank'}", 'b_verdict_keeps_gsfa_rank'),
 ('source.py', "            if len(page) < GSFA_LIMIT or any(type(x.get('blockTime')) is int and x['blockTime'] < window_start", "            if len(page) < GSFA_LIMIT or any(type(x.get('blockTime')) is int and x['blockTime'] < window_start + 10 ** 9", 'gsfa_collect_stops_early'),
 ('source.py', "            if not probe:\n                return []", "            if False:\n                return []", 'gtfa_probe_ignored'),
 ('source.py', "        if fresh:\n            self.last_sig[pool] =", "        if False:\n            self.last_sig[pool] =", 'gtfa_probe_never_armed'),
 ('source.py', "            if sig in self.seen[pool]:\n                continue", "            if False:\n                continue", 'gtfa_duplicates'),
 ('source.py', "            self.rank[pool][raw['slot']] = rank + 1\n            out.append(dict(raw, transactionIndex=rank, livepaper_index_source='gsfa_rank'))", "            self.rank[pool][raw['slot']] = rank\n            out.append(dict(raw, transactionIndex=rank, livepaper_index_source='gsfa_rank'))", 'rank_not_incremented'),
 ('source.py', "                self.rank[pool][raw['slot']] = rank + 1\n                self.seen[pool].add(s['signature'])", "                self.seen[pool].add(s['signature'])", 'catchup_rank_not_incremented'),
 ('source.py', "        sigs = [s for s in reversed(sigs) if not (type(s.get('blockTime')) is int and s['blockTime'] < self.start)", "        sigs = [s for s in reversed(sigs) if True", 'gsfa_pre_start_kept'),
 ('source.py', "GAP_FACTOR = 2", "GAP_FACTOR = 3", 'gap_factor_3'),
 ('source.py', "        if method not in METHODS:\n            raise RPC.RpcError('method_not_in_livepaper')", "        if False:\n            raise RPC.RpcError('method_not_in_livepaper')", 'transport_any_method'),
 ('source.py', "        if digest not in AUTHORIZED_TEXT_SHA256:", "        if False:", 'authorization_unchecked'),
 ('source.py', "    return not any('HELIUS' in k.upper() and 'KEY' in k.upper() for k in os.environ)", "    return True", 'key_check_disabled'),
 ('source.py', "    banned = ('solders.keypair', 'solana.keypair', 'nacl', 'solders.transaction', 'solana.transaction')", "    banned = ()", 'signing_check_disabled'),
 # cli.py
 ('cli.py', "    if type(ordercheck_sha) is not str or len(ordercheck_sha) != 64 or LS.file_sha(ordercheck_path) != ordercheck_sha:", "    if type(ordercheck_sha) is not str:", 'ordercheck_sha_unchecked'),
 ('cli.py', "    mode, poll_s = way(args.ordercheck, args.ordercheck_sha)", "    mode, poll_s = way(args.ordercheck, LS.file_sha(args.ordercheck))", 'ordercheck_sha_argument_ignored'),
 ('cli.py', "    if LS.file_sha(eligible_path) != eligible_sha:", "    if False:", 'eligible_sha_unchecked'),
 ('cli.py', "    if doc.get('schema') != ELIGIBLE_SCHEMA[variant]:", "    if False:", 'eligible_variant_unchecked'),
 ('cli.py', "    if type(start) is not int or start < doc['t_start']:", "    if type(start) is not int:", 'start_before_history_accepted'),
 ('cli.py', "        if cfg['sha256'] != by[x]['amm_config_sha256']:", "        if False:", 'config_sha_unchecked'),
 ('cli.py', "                         b3=by[x]['b3'], eligible=True))", "                         b3=2, eligible=True))", 'b3_not_from_eligible'),
 ('cli.py', "        window = doc['eligible_t_start'] - 7 * 86_400", "        window = doc['eligible_t_start']", 'gsfa_window_short'),
 ('cli.py', "            d = by_trigger.pop((name, sig), None)", "            d = by_trigger.get((name, sig), None)", 'compare_double_counts'),
 ('cli.py', "        if args.max_minutes > 115:", "        if args.max_minutes > 125:", 'process_above_115_accepted'),
 # 0.1.1: reserve 3, the replay module outside the MANIFESTs
 ('source.py', "    if got != (HRR_SHA256 if expected is None else expected):", "    if False:", 'hrr_sha_unchecked'),
 ('source.py', "AUTHORIZED_TEXT_SHA256 = frozenset({'31dfed474aa18a6e463bae0bf1e16d465a8edc0da8ad15362d1019f51ba66050'})", "AUTHORIZED_TEXT_SHA256 = frozenset({'31dfed474aa18a6e463bae0bf1e16d465a8edc0da8ad15362d1019f51ba66050', '1366025b6290c0a748c2190eebc5e3ee078a25868ef005591710b23658ebface'})", 'withdrawn_text_back'),
 # 0.1.3: timed calls, fetch_ms, GAP >=
 ('source.py', "                       duration_ms=(self.mono_ns() - start_ns) / 1e6, ok=error is None, error=error)", "                       duration_ms=(self.mono_ns() - start_ns) / 1e6, ok=True, error=error)", 'timing_ok_always'),
 ('source.py', "                       duration_ms=(self.mono_ns() - start_ns) / 1e6, ok=error is None, error=error)", "                       duration_ms=(self.mono_ns() - start_ns) / 1e9, ok=error is None, error=error)", 'timing_duration_seconds'),
 ('source.py', "            error = '%s:%s' % (type(exc).__name__, str(exc)[:80])\n            raise", "            error = '%s:%s' % (type(exc).__name__, str(exc)[:80])\n            return None", 'timing_swallows_errors'),
 ('source.py', "                             clock_ns=self.mono_ns, fetch_ms=(fetched - began) / 1e6)", "                             clock_ns=self.mono_ns, fetch_ms=None)", 'fetch_ms_dropped'),
 ('source.py', "        if last_wall is not None and wall - last_wall >= GAP_FACTOR * self.poll_s:", "        if last_wall is not None and wall - last_wall > GAP_FACTOR * self.poll_s:", 'gap_strict'),
 ('journal.py', "VOLATILE = ('wall', 'mono_ns', 'processing_ms', 'fetch_ms')", "VOLATILE = ('wall', 'mono_ns', 'processing_ms')", 'fetch_ms_not_volatile'),
 ('cli.py', "    client = S.RetryOnce(S.TimedClient(RPC.Client(transport, S.Budget(args.ledger), args.calls),\n                                       str(args.calls) + '.timing.jsonl'), args.calls)", "    client = S.RetryOnce(RPC.Client(transport, S.Budget(args.ledger), args.calls), args.calls)", 'run_not_timed'),
 ('cli.py', "        client = S.RetryOnce(S.TimedClient(RPC.Client(transport, S.Budget(args.ledger), args.calls),\n                                           str(args.calls) + '.timing.jsonl'), args.calls)", "        client = S.RetryOnce(RPC.Client(transport, S.Budget(args.ledger), args.calls), args.calls)", 'collect_not_timed'),
 ('cli.py', "    S.check_imports()\n    mode, poll_s = way(args.ordercheck, args.ordercheck_sha)", "    mode, poll_s = way(args.ordercheck, args.ordercheck_sha)", 'run_without_import_check'),
 ('cli.py', "        S.check_imports()\n        doc = json.loads(args.pools.read_text())", "        doc = json.loads(args.pools.read_text())", 'collect_without_import_check'),
 # ordercheck.py
 ('ordercheck.py', "            gsfa_a_later = position[a][1] < position[b][1]", "            gsfa_a_later = position[a][1] > position[b][1]", 'gsfa_order_reversed'),
 ('ordercheck.py', "    verdict = 'a-ok' if pairs > 0 and bad == 0 else 'b'", "    verdict = 'a-ok' if bad == 0 else 'b'", 'a_ok_without_pairs'),
 ('ordercheck.py', "    bad = sum(v['discrepancies'] + v['slot_mismatches'] for v in per.values())", "    bad = sum(v['discrepancies'] for v in per.values())", 'slot_mismatch_ignored'),
 ('ordercheck.py', "    mismatched = sorted(sig for sig in both if position[sig][0] != gtfa[sig][0])", "    mismatched = []", 'slot_mismatch_not_found'),
 ('ordercheck.py', "        position.setdefault(s['signature'], (s['slot'], k))", "        position[s['signature']] = (s['slot'], -k)", 'gsfa_position_inverted'),
 # engine: WAIT, MARK, frozen way
 ('engine.py', "                if not ok:\n                    self.journal.append('WAIT'", "                if False:\n                    self.journal.append('WAIT'", 'wait_not_recorded'),
 ('engine.py', "                                        reasons=list(gate['reasons']) + ([] if row['b3'] > 0 else ['b3_zero']))", "                                        reasons=list(gate['reasons']))", 'wait_without_b3_reason'),
 ('engine.py', "        if self.mark_hour is not None and hour != self.mark_hour:", "        if False:", 'marks_never'),
 ('engine.py', "                if pos['status'] != 'landed':\n                    continue", "                if pos['status'] == 'closed':\n                    continue", 'mark_before_landing'),
 ('engine.py', "                                    mark_time=hour * 3_600, value_lamports=value,", "                                    mark_time=hour * 3_600 + 1, value_lamports=value,", 'mark_time_off'),
 ('engine.py', "                            start=start, seed_sha=seed_sha, variant=variant, mode=mode, poll_s=poll_s,", "                            start=start, seed_sha=seed_sha, variant=variant,", 'way_not_in_start'),
 ('source.py', "            self.last_sig, self.rank, self.since, self.seen = saved\n            raise\n        return batch, slot", "            raise\n        return batch, slot", 'fetch_not_restored'),
 ('source.py', "                {p: set(s) for p, s in self.seen.items()})", "                dict(self.seen))", 'restore_shallow_seen'),
 ('source.py', "{p: dict(r) for p, r in self.rank.items()}", "dict(self.rank)", 'restore_shallow_rank'),
 ('source.py', "        except BaseException:\n            self.last_sig, self.rank, self.since, self.seen = saved\n            raise\n        return batch, slot", "        except SourceError:\n            self.last_sig, self.rank, self.since, self.seen = saved\n            raise\n        return batch, slot", 'restore_only_source_errors'),
 ('engine.py', "SCHEMA = 'livepaper-v0.1.5'", "SCHEMA = 'livepaper-v0.1.4'", 'schema_not_bumped'),
 ('journal.py', "RUNNER_KINDS = ('CATCHUP', 'ERROR', 'STOP')", "RUNNER_KINDS = ('CATCHUP', 'STOP')", 'error_not_skipped'),
 ('source.py', "        j.append('ERROR', error_type=type(exc).__name__, message=redact(exc), wall=self.wall())\n", "", 'error_not_journaled'),
 ('source.py', "                return self._error_stop(exc)", "                self.sleep(self.poll_s)\n                continue", 'incident_tolerated'),
 ('source.py', "            if self.retry != 1 or str(exc) != 'response_truncated':", "            if self.retry != 1:", 'retry_any_error'),
 ('source.py', "retry=True,\n", "retry=False,\n", 'retry_logged_false'),
 ('source.py', "RETRY_ON_TRUNCATED = 1 ", "RETRY_ON_TRUNCATED = 0 ", 'retry_default_off'),
 ('source.py', "            return self.client.call(method, params)\n\n\nclass TimedClient", "            try:\n                return self.client.call(method, params)\n            except RPC.RpcError:\n                return self.client.call(method, params)\n\n\nclass TimedClient", 'retry_twice'),
 ('source.py', "for c in str(exc))[:80]", "for c in str(exc))", 'redact_unbounded'),
 ('source.py', "c in '_:.-') else '?'", "c in '_:.-/= ') else '?'", 'redact_keeps_url_chars'),
 ('source.py', "        return self._stop('incident:%s' % type(exc).__name__)", "        return self._stop('incident')", 'stop_reason_without_type'),
 ('cli.py', "    client = S.RetryOnce(S.TimedClient(RPC.Client(transport, S.Budget(args.ledger), args.calls),\n                                       str(args.calls) + '.timing.jsonl'), args.calls)", "    client = S.TimedClient(RPC.Client(transport, S.Budget(args.ledger), args.calls), str(args.calls) + '.timing.jsonl')", 'run_without_retry'),
 ('source.py', "        for pool in self.engine.breaks_ahead(batch, receipt_time):", "        for pool in []:", 'catchup_disabled'),
 ('source.py', "            self.engine.journal.append('CATCHUP',", "            (lambda *a, **k: None)('CATCHUP',", 'catchup_not_journaled'),
 ('source.py', "            if any(self.rank[pool].get(s['slot'], 0) for s in missed):", "            if False:", 'catchup_rank_unchecked'),
 ('source.py', "            if len(missed) > CATCHUP_MAX_TX:", "            if False:", 'catchup_unbounded'),
 ('source.py', "s['slot'] <= min(newest, receipt_slot)", "s['slot'] <= newest", 'catchup_after_receipt'),
 ('source.py', "        except BaseException:\n            self.last_sig, self.rank, self.since, self.seen = saved\n            raise\n        return out, 'found'", "        except BaseException:\n            raise\n        return out, 'found'", 'catchup_not_restored'),
 ('source.py', "        if self.mode != 'gsfa_rank':\n            return [], 'not_in_gtfa_mode'\n", "", 'catchup_in_gtfa'),
 ('source.py', "livepaper_index_source='gsfa_rank_catchup'", "livepaper_index_source='gsfa_rank'", 'catchup_index_source_hidden'),
 ('source.py', "CATCHUP_GSFA_LIMIT, CATCHUP_MAX_TX = 100, 10", "CATCHUP_GSFA_LIMIT, CATCHUP_MAX_TX = 1000, 10", 'catchup_limit_as_poll'),
 ('engine.py', "            if self.g0[pool] is not None and BROKEN in self.g0[pool]['reasons']:\n                continue\n", "", 'catchup_every_step'),
 ('journal.py', "RUNNER_KINDS = ('CATCHUP', 'ERROR', 'STOP')", "RUNNER_KINDS = ('ERROR', 'STOP')", 'catchup_not_skipped'),
 ('source.py', "METHODS = ('getSlot', 'getSignaturesForAddress', 'getTransaction', 'getTransactionsForAddress')", "METHODS = ('getSlot', 'getSignaturesForAddress', 'getTransaction', 'getTransactionsForAddress', 'getBalance')", 'methods_extra'),
 ('source.py', "                    self.last_sig, self.rank, self.since, self.seen = saved\n                    return [], 'not_served'", "                    return [], 'not_served'", 'catchup_not_served_not_restored'),
 ('source.py', "        check_resumable(self.engine.journal.records, loaded=self.engine.journal.loaded)\n", "", 'resumable_unchecked_by_runner'),
 ('cli.py', "        S.check_resumable(J.read(args.journal))", "        pass", 'resumable_unchecked_by_cli'),
 ('cli.py', "    S.check_window(pools_doc['start'],", "    (lambda *a: None)(pools_doc['start'],", 'window_unchecked_by_cli'),
 ('source.py', "        check_window(self.engine.start, self.wall())\n", "", 'window_unchecked_by_runner'),
 ('source.py', "    if wall >= start + TEST_S:", "    if wall > start + TEST_S:", 'window_strict'),
 ('source.py', "            if self.wall() >= self.engine.start + TEST_S:\n                return self._stop('end_of_test_86400')\n", "", 'no_end_of_test'),
 ('source.py', "            if self.wall() >= self.engine.start + TEST_S:", "            if self.wall() > self.engine.start + TEST_S:", 'end_of_test_strict'),
 ('source.py', "TEST_S = 86_400 ", "TEST_S = 86_401 ", 'test_window_longer'),
 ('cli.py', "        S.check_window(doc['start'], (kw.get('clocks') or {}).get('wall', time.time)())   # 0.1.5 (c), R02 03:09Z\n        transport", "        transport", 'collect_window_unchecked'),
 ('cli.py', "        S.check_window(doc['start'], (kw.get('clocks') or {}).get('wall', time.time)())   # 0.1.5 (c), R02 03:09Z\n        print(_write", "        print(_write", 'ordercheck_window_unchecked'),
 ('source.py', "    if disk:\n        last = disk[-1]", "    if False:\n        last = disk[-1]", 'rule_removed'),
 ('source.py', "        if last['kind'] != 'STOP' or last['reason'] != PLANNED_STOP:", "        if last['kind'] != 'STOP':", 'rule_any_stop_accepted'),
 ('source.py', "        if last['kind'] != 'STOP' or last['reason'] != PLANNED_STOP:", "        if last.get('reason', PLANNED_STOP) != PLANNED_STOP:", 'rule_killed_journal_accepted'),
 ('source.py', "        if last['kind'] != 'STOP' or last['reason'] != PLANNED_STOP:", "        if last['kind'] == 'ERROR' or last.get('reason', PLANNED_STOP) != PLANNED_STOP:", 'rule_only_error_refused'),
 ('source.py', "check_resumable(self.engine.journal.records, loaded=self.engine.journal.loaded)", "check_resumable(self.engine.journal.records)", 'runner_loaded_ignored'),
 ('source.py', "check_resumable(self.engine.journal.records, loaded=self.engine.journal.loaded)", "check_resumable(self.engine.journal.records, loaded=0)", 'runner_disk_unchecked'),
 ('journal.py', "        self.loaded = len(self.records) ", "        self.loaded = 0 ", 'loaded_always_zero'),
 ('source.py', "    for r in records:\n        if r['kind'] == 'ERROR' or (r['kind'] == 'STOP' and r['reason'].startswith(FINAL_STOPS)):\n            raise SourceError('journal_stopped_for_good:%s' % r.get('reason', r['kind']))\n", "", 'nowhere_condition_removed'),
 ('source.py', "        if r['kind'] == 'ERROR' or (r['kind'] == 'STOP' and r['reason'].startswith(FINAL_STOPS)):", "        if r['kind'] == 'STOP' and r['reason'].startswith(FINAL_STOPS):", 'nowhere_error_ignored'),
 ('source.py', "FINAL_STOPS = ('incident:', 'credit_hard_stop', 'end_of_test_86400')", "FINAL_STOPS = ('incident:', 'credit_hard_stop')", 'nowhere_end_of_test_ignored'),
 ('source.py', "FINAL_STOPS = ('incident:', 'credit_hard_stop', 'end_of_test_86400')", "FINAL_STOPS = ('incident:', 'end_of_test_86400')", 'nowhere_credit_stop_ignored'),
]


def run(work):
    return subprocess.run([V, '-B', '-m', 'pytest', str(work / 'livepaper' / 'tests'), '-p', 'no:cacheprovider', '-q', '-x', '-W', 'error'],
                          cwd=W, env={'PYTHONPATH': f'{PP}:{work}', 'PATH': '/usr/bin:/bin', 'RUGGER_NO_DOTENV': '1'}, capture_output=True, text=True)
PUBLISHED = 'METHODS_livepaper_v0_1_4.txt'          # 0.1.4 (D15): the published list, read by the tests


def copy(work):
    shutil.copytree(D / 'livepaper', work / 'livepaper', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy(D / PUBLISHED, work / PUBLISHED)


base = M / '_baseline'
copy(base)
if run(base).returncode != 0:
    print(json.dumps(dict(error='baseline_does_not_pass'))); sys.exit(2)
for f, old, new, name in MUT:
    assert (D / 'livepaper' / f).read_text().count(old) == 1, name
def one(m):
    f, old, new, name = m
    work = M / name
    copy(work)
    p = work / 'livepaper' / f
    p.write_text(p.read_text().replace(old, new))
    return dict(mutant=name, file=f, detected=run(work).returncode != 0)
with ThreadPoolExecutor(4) as ex:
    out = list(ex.map(one, MUT))
print(json.dumps(out, indent=1)); print(sum(o['detected'] for o in out), '/', len(out))
