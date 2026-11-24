"""Mutation runner of cpmmpilot (K-1 of R02 audit 0b3a3033): base guard (the unmutated copy must pass), then every
mutant must make the test suite FAIL. Each mutant replaces exactly one occurrence of a code fragment.

  PYTHONPATH=<frozen deps without cpmmpilot_pkg> python -B mutations_cpmmpilot_runner.py --deps-pythonpath <...> --out <json>
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MUTANTS = [
    # R02's four survivors of 0.1
    ('charge_after', 'rpc.py', '        self.budget.charge(method, params)              # ledger on disk before the request leaves\n        result = self.transport.request(method, params)\n',
     '        result = self.transport.request(method, params)\n        self.budget.charge(method, params)\n'),
    ('seed_changed', 'u2.py', 'random.Random(int(sha_l[:8], 16)).shuffle(order)', 'random.Random(int(sha_l[:7], 16)).shuffle(order)'),
    ('reserve_50', 'u2.py', 'MIN_RESERVE_LAMPORTS = 100 * 10 ** 9', 'MIN_RESERVE_LAMPORTS = 50 * 10 ** 9'),
    ('floor_ignored', 'u2.py', "verdict = 'INCONCLUSIF' if len(valid) < FLOOR else 'U2_OK'", "verdict = 'U2_OK'"),
    # budget and stop rules
    ('reserve_strict', 'u2.py', 'amount < MIN_RESERVE_LAMPORTS', 'amount <= MIN_RESERVE_LAMPORTS'),
    ('hard_stop_50000', 'budget.py', 'STEP1_HARD_STOP = 49_000', 'STEP1_HARD_STOP = 50_000'),
    # 0.2.8: G2-3 stage
    ('g23_cap_33000', 'budget.py', 'G23_CAP = 32_340', 'G23_CAP = 33_000'),
    ('g23_stage_missing', 'budget.py', "('step0', 'u2', 'step1', 't2', 'g23')", "('step0', 'u2', 'step1', 't2')"),
    ('point2_ge', 'budget.py', 'stop=need > POINT2_LIMIT', 'stop=need >= POINT2_LIMIT + 100'),
    ('gtfa_cost_1', 'budget.py', "'getTransactionsForAddress': 10}", "'getTransactionsForAddress': 1}"),
    ('ledger_not_resumed', 'budget.py', "            self.requests, self.credits = data['requests'], data['credits']\n", ''),
    ('gtfa_limit_unchecked', 'budget.py', "            if type(limit) is not int or not 1 <= limit <= GTFA_MAX_LIMIT:\n                raise BudgetError('gtfa_limit_must_be_1_to_100')\n", ''),
    # U-2
    ('gtfa_fallback', 'u2.py', "        except MethodRefused as exc:\n            raise U2Stop('gtfa_refused_no_fallback:%s' % exc) from exc\n",
     "        except MethodRefused:\n            continue\n"),
    ('launchlab_ignored', 'u2.py', "        if LAUNCHLAB_PROGRAM in parts:\n            return False, 'launchlab_in_creation_transaction'\n", ''),
    ('depth_ignored', 'u2.py', "    if init_depth != 1:\n        return False, 'initialize_not_at_depth_1'\n", ''),
    ('age_6_days', 'u2.py', 'MIN_AGE_S = 7 * 86_400', 'MIN_AGE_S = 6 * 86_400'),
    ('target_25', 'u2.py', 'TARGET, FLOOR = 24, 20', 'TARGET, FLOOR = 25, 20'),
    ('token2022_excluded_again', 'u2.py', "                elif pool in exclude:", "                elif L.TOKEN_2022 in (p['token_0_program'], p['token_1_program']):\n                    continue\n                elif pool in exclude:"),
    ('status_not_checked', 'u2.py', "                if p['status'] & 4:", "                if False:"),
    # step 1
    ('anchor_not_checked', 'step1.py', "            raise Step1Stop('freeze_sheet_not_anchored:%s' % name)", '            pass'),
    ('resume_from_zero', 'step1.py', "        state = read_json(state_path) if state_path.exists() else dict(", "        state = dict("),
    ('g0_forced_true', 'step1.py', 'g0_passed=g0_passed, freeze_sheet_sha256', 'g0_passed=True, freeze_sheet_sha256'),
    ('count_window_wide', 'step1.py', 'if t0_time - DAY <= (s.get(\'blockTime\') or 0) < t0_time', 'if t0_time - 2 * DAY <= (s.get(\'blockTime\') or 0) < t0_time'),
    # 0.1.2: K01 / K02
    ('unpriced_dropped', 'step1.py', "    return [r if 'net_return' in r else\n            zero_sale(dict(r, decision_slot=line.swaps[r['decision_index']].slot), failures) for r in rows]\n",
     "    return [r for r in rows if 'net_return' in r]\n"),
    ('zero_sale_without_wsol', 'step1.py', '    wsol_close = CC.TX_FEE_LAMPORTS if wsol_separate_close else 0\n', '    wsol_close = 0\n'),
    ('vocabulary_unchecked', 'step1.py', "        raise Step1Stop('forbidden_word_in_output:%s' % ','.join(found))", '        pass'),
    # 0.1.4: zero sale with the failures of a series
    ('zero_sale_failures_ignored', 'step1.py', '    tx_buy = (1 + failures.buy) * CC.TX_FEE_LAMPORTS\n', '    tx_buy = CC.TX_FEE_LAMPORTS\n'),
    # 0.1.6: erratum R02 (6f071c5a) -- three failed cleanups leave the account open
    ('rent_forgotten_at_cleanup_3', 'step1.py', '        cleanup, rent_lost = failures.cleanup * CC.TX_FEE_LAMPORTS, CC.TOKEN_ACCOUNT_RENT_LAMPORTS\n',
     '        cleanup, rent_lost = (failures.cleanup + 1) * CC.TX_FEE_LAMPORTS, 0\n'),
    ('cleanup_branch_never', 'step1.py', '    if failures.cleanup == CA.MAX_CLEANUP_ATTEMPTS:\n', '    if False:\n'),
    # 0.1.5: g1ind 0.3 (R01, PASS R02) fed with converted rows, the four sensitivities and the cut of the sheet
    ('sensitivity_failures_ignored', 'step1.py', "_converted(line, rule.positions(line, cfg, idx, **kw), kw.get('failures', CC.FROZEN_FAILURES))",
     "_converted(line, rule.positions(line, cfg, idx, **kw))"),
    ('placebo_not_converted', 'step1.py', "placebo += _converted(line, rule.positions(line, cfg, rule.placebo(line, len(idx), sheets[name])))",
     "placebo += rule.positions(line, cfg, rule.placebo(line, len(idx), sheets[name]))"),
    ('sensitivities_not_passed', 'step1.py', 'cut_time=cut_time, sensitivities=sens, lines=admitted', 'cut_time=cut_time, lines=admitted'),
    ('cut_time_not_passed', 'step1.py', 'cut_time=cut_time, sensitivities=sens', 'cut_time=None, sensitivities=sens'),
    ('sheet_cut_not_middle', 'step1.py', "int(d_days * DAY) // 2,", "int(d_days * DAY) // 3,"),
    ('decision_slot_missing', 'step1.py', "zero_sale(dict(r, decision_slot=line.swaps[r['decision_index']].slot), failures)", "zero_sale(r, failures)"),
    ('latency_sensitivity_4_slots', 'step1.py', 'latency_10_slots=dict(latency_slots=CC.SENSITIVITY_LATENCY_SLOTS)', 'latency_10_slots=dict(latency_slots=CC.LATENCY_SLOTS)'),
    # 0.2.3: D rule (R02 e294655a)
    ('d_min_7_ignored', 'step1.py', '        lower = max(d155, D_MIN)\n', '        lower = d155\n'),
    ('d_cap_60_ignored', 'step1.py', '    d = min(lower, math.floor(d_max_days), D_CAP)\n', '    d = min(lower, math.floor(d_max_days))\n'),
    ('d_max_ignored', 'step1.py', '    d = min(lower, math.floor(d_max_days), D_CAP)\n', '    d = min(lower, D_CAP)\n'),
    ('d155_floor_not_ceil', 'step1.py', '        d155 = -(-D_TARGET_ENTRIES * 7 // t)', '        d155 = D_TARGET_ENTRIES * 7 // t'),
    ('d155_target_150', 'step1.py', 'D_TARGET_ENTRIES, D_MIN, D_CAP = 155, 7, 60', 'D_TARGET_ENTRIES, D_MIN, D_CAP = 150, 7, 60'),
    ('d_rule_not_in_sheets', 'step1.py', 'frozen_rules=CC.frozen_check(), d_rule=d_rule)', 'frozen_rules=CC.frozen_check())'),
    ('d_rule_mismatch_unchecked', 'step1.py', "        raise Step1Stop('d_rule_differs_from_d_days')\n", '        pass\n'),
    # 0.2.5: v1 transactions, version error, redacted text (R02 f2e62c72)
    ('max_version_0', 'rpc.py', 'MAX_TX_VERSION = 1 ', 'MAX_TX_VERSION = 0 '),
    ('collect_version_literal_0', 'step1.py', 'maxSupportedTransactionVersion=MAX_TX_VERSION, filters', 'maxSupportedTransactionVersion=0, filters'),
    ('u2_version_literal_0', 'u2.py', '                maxSupportedTransactionVersion=MAX_TX_VERSION)])', '                maxSupportedTransactionVersion=0)])'),
    ('version_error_as_refusal', 'rpc.py', "            if TX_VERSION_WORDS in text:", "            if False:"),
    ('error_text_not_recorded', 'rpc.py', "            exc.error_text = redact_error_text(text)\n", ''),
    ('error_text_not_redacted', 'rpc.py', "        out.append(REDACT_MARK if ('http' in seg or 'api' in seg or 'key' in seg or len(seg) > 32) else seg)", "        out.append(seg)"),
    ('redact_long_40', 'rpc.py', "or len(seg) > 32) else seg)", "or len(seg) > 40) else seg)"),
    ('error_text_not_cut', 'rpc.py', "    return ' '.join(out)[:ERROR_TEXT_MAX]", "    return ' '.join(out)"),
    ('format_guard_removed', 'step1.py', "                    raise TxFormatStop('STOP_TX_FORMAT:%s' % problem)\n", "                    pass\n"),
    ('format_meta_unchecked', 'step1.py', "    if not isinstance(meta, dict) or (meta.get('logMessages') is None and meta.get('err') is None):", "    if not isinstance(meta, dict):"),
    ('format_blocktime_unchecked', 'step1.py', "    for key in ('slot', 'transactionIndex', 'blockTime'):", "    for key in ('slot', 'transactionIndex'):"),
    # 0.2.7: truncated HTTP responses, per-pool checkpoints (R02 822d5edf)
    ('http_exception_uncaught', 'rpc.py', "        except http.client.HTTPException:                                    # 0.2.7: IncompleteRead and kin (R02 822d5edf)\n            raise RpcError('response_truncated') from None\n", ''),
    ('checkpoint_not_written', 'step1.py', "        if checkpoint is not None:                    # 0.2.7: counts written after EACH pool, so a STOP keeps them\n", "        if False:\n"),
    # 0.2: live transport (R02 note fb28705b) -- gated, no host or key read, no retry, nothing echoed
    ('release_authorizes_another_sha', 'rpc.py', "AUTHORIZED_TEXT_SHA256 = frozenset({'e25389f014503e5fb98317bfc502ca4998b4d149453a0b10f95ec3d21aea26a1',",
     "AUTHORIZED_TEXT_SHA256 = frozenset({'e25389f014503e5fb98317bfc502ca4998b4d149453a0b10f95ec3d21aea26a1', '0' * 64,"),
    ('t2_cap_1500', 'budget.py', 'T2_CAP = 1_470 ', 'T2_CAP = 1_500 '),
    # 0.2.1: U-2 in two times
    ('u2_anchor_not_checked', 'u2.py', "    if sha(lst) != doc['sha256'] or doc['sha256'] != anchored_sha_l:\n        raise U2Stop('list_l_not_anchored')\n", ''),
    ('u2_list_not_rehashed', 'u2.py', "if sha(lst) != doc['sha256'] or doc['sha256'] != anchored_sha_l:", "if doc['sha256'] != anchored_sha_l:"),
    ('u2_first_time_continues', 'u2.py', "    return dict(schema=SCHEMA, verdict='LIST_L_AWAITS_R02_ANCHOR',", "    return run_qualify(client, out, anchored_sha_l=sha_l) or dict(schema=SCHEMA, verdict='LIST_L_AWAITS_R02_ANCHOR',"),
    ('authorization_not_checked', 'rpc.py', "        if digest not in AUTHORIZED_TEXT_SHA256:\n            raise RpcError('authorization_not_anchored')\n", ''),
    ('authorization_file_optional', 'rpc.py', "        if authorization_file is None:\n            raise RpcError('live_rpc_needs_an_anchored_authorization')\n", ''),
    ('http_allowed', 'rpc.py', "if u.scheme != 'https' or not u.hostname:", 'if not u.hostname:'),
    ('query_allowed', 'rpc.py', 'if u.username or u.password or u.query or u.fragment:', 'if u.username or u.password or u.fragment:'),
    ('key_path_allowed', 'rpc.py', "    if any(w in u.path.lower() for w in ('key', 'token', 'secret')):\n        raise RpcError('endpoint_must_not_carry_credentials')\n", ''),
    ('method_unchecked', 'rpc.py', "        if method not in PILOT_METHODS:\n            raise RpcError('method_not_in_pilot')\n", ''),
    ('size_unbounded', 'rpc.py', "        if len(raw) > MAX_RESPONSE_BYTES:\n            raise RpcError('response_too_large')\n", ''),
    ('id_unchecked', 'rpc.py', " or payload.get('id') != rid:", ':'),
    ('refusal_not_mapped', 'rpc.py', 'if code == METHOD_NOT_FOUND or any(w in text for w in REFUSAL_WORDS):', 'if False:'),
    ('message_echoed', 'rpc.py', "                exc = RpcError('rpc_error:' + tag)", "                exc = RpcError('rpc_error:' + text)"),
    ('network_detail_echoed', 'rpc.py', "        except (urllib.error.URLError, OSError, ValueError):\n            raise RpcError('network_error') from None",
     "        except (urllib.error.URLError, OSError, ValueError) as exc:\n            raise RpcError('network_error:%s' % exc) from None"),
    ('cause_kept', 'rpc.py', "raise RpcError('http_%d' % exc.code) from None", "raise RpcError('http_%d' % exc.code) from exc"),
    ('repr_leaks_endpoint', 'rpc.py', "return 'LiveRpc(authorization_sha256=%s)' % self.authorization_sha256", "return 'LiveRpc(%s)' % self._endpoint"),
    ('rate_limit_not_mapped', 'rpc.py', "            if exc.code == 429:\n                raise RpcError('rate_limited_429') from None\n", ''),
    # 0.2.2: spacing (R02 note 41c20a16)
    ('spacing_removed', 'rpc.py', "            if wait > 0:\n                self._sleep(wait)\n", ''),
    ('spacing_0_1', 'rpc.py', 'MIN_INTERVAL_S = 0.2 ', 'MIN_INTERVAL_S = 0.1 '),
    ('last_sent_not_updated', 'rpc.py', '        self._last_sent = self._clock()\n', ''),
]


def run_tests(pkg_root, deps):
    env = dict(PATH='/usr/bin:/bin', RUGGER_NO_DOTENV='1', PYTHONPATH=deps + ':' + str(pkg_root))
    r = subprocess.run([sys.executable, '-B', '-m', 'pytest', str(pkg_root / 'cpmmpilot' / 'tests'), '-p',
                        'no:cacheprovider', '-q', '-x', '-W', 'error'], env=env, capture_output=True, text=True,
                       cwd=os.getcwd())
    return r.returncode


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--deps-pythonpath', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / 'base'
        shutil.copytree(HERE, base, ignore=shutil.ignore_patterns('__pycache__'))
        results['_base_guard'] = 'PASS' if run_tests(base, a.deps_pythonpath) == 0 else 'FAIL'
        if results['_base_guard'] != 'PASS':
            raise SystemExit('base_guard_failed')
        for name, fname, old, new in MUTANTS:
            d = Path(tmp) / name
            shutil.copytree(HERE, d, ignore=shutil.ignore_patterns('__pycache__'))
            f = d / 'cpmmpilot' / fname
            text = f.read_text()
            if text.count(old) != 1:
                results[name] = 'INVALID (fragment found %d times)' % text.count(old)
                continue
            f.write_text(text.replace(old, new))
            results[name] = 'KILLED' if run_tests(d, a.deps_pythonpath) != 0 else 'SURVIVED'
    killed = sum(v == 'KILLED' for v in results.values())
    doc = dict(schema='cpmmpilot-mutations-v0.2.8', base_guard=results.pop('_base_guard'), mutants=len(MUTANTS),
               killed=killed, results=results)
    a.out.write_text(json.dumps(doc, indent=1, sort_keys=True) + '\n')
    print(json.dumps(dict(killed=killed, mutants=len(MUTANTS), survived=[k for k, v in results.items() if v != 'KILLED'])))
    return 0 if killed == len(MUTANTS) else 1


if __name__ == '__main__':
    raise SystemExit(main())
