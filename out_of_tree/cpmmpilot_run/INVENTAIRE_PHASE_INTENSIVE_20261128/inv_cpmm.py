"""Offline inventory of CPMM list L (inventory only: no price/return/PnL)."""
import collections, gzip, hashlib, json, os, sys

BASE = '/home/user/rugger_bot_v1/out_of_tree/cpmmpilot_run'
OUT = sys.argv[1]
FORBIDDEN = ('p0/', 'P0_SCELLE', '9f19ccac', 'sauvegarde_20261110')
CPMM = 'CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C'
WSOL = 'So11111111111111111111111111111111111111112'
PILOT_PREFIX = ('AEZjoU', 'Gms3Ma', 'G8kgi7', 'GdxFyc')
DISC = {hashlib.sha256(b'global:' + n.encode()).digest()[:8]: n for n in ('swap_base_input', 'swap_base_output')}
INIT_DISC = {hashlib.sha256(b'global:' + n.encode()).digest()[:8]: n for n in ('initialize', 'initialize_with_permission')}
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
IDX = {c: i for i, c in enumerate(B58)}
ND = 'non disponible'
ANCHORS = {
    'TIME1R_20261124T102126Z/LIST_L.json': 'c96353b9f3c0bdb25fd1b7c8af85cf0c4efd66e84480d7850252b85d8a7d8ff3',
    'TIME2_20261124T102839Z/U2.json': '3ca0260a',
    'CREATOR_FEE_FLAGS_20261125/FLAGS_LIST_L.json': '5c44f641',
    'STEP1A2R_20261124T164909Z/SHA256SUMS_PRE_PAGES.txt': '8fb3cac4',
    'LIVESIM_20261125T113851Z/SHA256SUMS_PRE_PAGES.txt': '951b8479',
}
# sums file -> directory its "./" paths are relative to
SUMS = {
    'STEP1A2R_20261124T164909Z/SHA256SUMS_PRE_PAGES.txt': 'STEP1A2R_20261124T164909Z/pre_pages',
    'STEP1A2R_20261124T164909Z/SHA256SUMS_PRE_STATES.txt': 'STEP1A2R_20261124T164909Z/pre_pages',
    'LIVESIM_20261125T113851Z/SHA256SUMS_PRE_PAGES.txt': 'LIVESIM_20261125T113851Z/collect/pre',
    'LIVESIM_20261125T113851Z/SHA256SUMS_PRE_STATES.txt': 'LIVESIM_20261125T113851Z/collect/pre',
    'LIVESIM_20261125T113851Z/SHA256SUMS_LIVE_PAGES_T6H.txt': 'LIVESIM_20261125T113851Z/collect',
    'LIVESIM_20261125T113851Z/SHA256SUMS_LIVE_PAGES_T24H.txt': 'LIVESIM_20261125T113851Z/collect',
    'LIVESIM_20261125T113851Z/SHA256SUMS_LIVE_STATES_T6H.txt': 'LIVESIM_20261125T113851Z/collect',
    'LIVESIM_20261125T113851Z/SHA256SUMS_LIVE_STATES_T24H.txt': 'LIVESIM_20261125T113851Z/collect',
}


def guard(p):
    if any(f in p for f in FORBIDDEN):
        raise SystemExit('forbidden path refused: ' + p)
    return p


def sha(p):
    h = hashlib.sha256()
    with open(guard(p), 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def b58d(t):
    n = 0
    for c in t:
        n = n * 58 + IDX[c]
    raw = n.to_bytes((n.bit_length() + 7) // 8, 'big') if n else b''
    return b'\0' * (len(t) - len(t.lstrip('1'))) + raw


def keys_of(tx):
    ks = [k if isinstance(k, str) else k['pubkey'] for k in tx['transaction']['message']['accountKeys']]
    la = tx['meta'].get('loadedAddresses') or {}
    return ks + list(la.get('writable') or []) + list(la.get('readonly') or [])


def cpmm_ixs(tx, ks):
    ixs = list(tx['transaction']['message']['instructions'])
    for g in tx['meta'].get('innerInstructions') or []:
        ixs.extend(g['instructions'])
    for ix in ixs:
        if ks[ix['programIdIndex']] != CPMM:
            continue
        try:
            raw = b58d(ix['data'])
        except KeyError:
            continue
        yield raw[:8], [ks[i] for i in ix['accounts']]


def schema(o):
    if isinstance(o, dict):
        return {k: schema(v) for k, v in o.items()}
    if isinstance(o, list):
        return [schema(o[0])] if o else []
    return type(o).__name__


def p(rel):
    return os.path.join(BASE, guard(rel))


def main():
    meta = {'anchors': {}, 'sums_verification': {}}
    for rel, exp in ANCHORS.items():
        h = sha(p(rel))
        meta['anchors'][rel] = {'sha256': h, 'expected': exp, 'ok': h.startswith(exp)}
        if not h.startswith(exp):
            raise SystemExit('anchor mismatch ' + rel)
    verified = set()
    for rel, root in SUMS.items():
        ok, bad, miss = 0, [], []
        for line in open(p(rel)):
            if not line.strip():
                continue
            h, f = line.split(None, 1)
            f = f.strip()
            fp = os.path.normpath(os.path.join(p(root), f))
            if not os.path.exists(fp):
                miss.append(f); continue
            if sha(fp) != h:
                bad.append(f); continue
            ok += 1; verified.add(fp)
        meta['sums_verification'][rel] = {'sha256': sha(p(rel)), 'relative_to': root, 'ok': ok,
                                          'mismatched': bad, 'missing': miss}
    # files present in page dirs but not covered by any sums file
    uncovered = []
    for root in sorted(set(SUMS.values())):
        for dp, dn, fn in os.walk(p(root)):
            dn[:] = [d for d in dn if not any(x in os.path.join(dp, d) + '/' for x in FORBIDDEN)]
            if root.endswith('/collect') and os.path.basename(dp) == 'collect':
                dn[:] = [d for d in dn if d != 'pre']
            for f in fn:
                fp = os.path.join(dp, f)
                if fp not in verified:
                    uncovered.append(os.path.relpath(fp, BASE))
    meta['files_not_covered_by_sums_not_used'] = uncovered
    L = json.load(open(p('TIME1R_20261124T102126Z/LIST_L.json')))
    U2 = json.load(open(p('TIME2_20261124T102839Z/U2.json')))
    FL = json.load(open(p('CREATOR_FEE_FLAGS_20261125/FLAGS_LIST_L.json')))
    meta['cross_checks'] = {'LIST_L.sha256_field_eq_U2.sha_l': L.get('sha256') == U2.get('sha_l'),
                            'U2.anchored_sha_l_eq_U2.sha_l': U2.get('anchored_sha_l') == U2.get('sha_l'),
                            'LIST_L.t0_slot_eq_U2.t0_slot': L['t0_slot'] == U2['t0_slot'],
                            'flags_cover_all_L': set(FL) == {e['pool'] for e in L['list']},
                            'U2_selected_in_L': all(s['pool'] in {e['pool'] for e in L['list']} for s in U2['selected'])}
    u2sel = {s['pool']: s for s in U2['selected']}

    # page sources: name -> {pool: [page_dir,...]}
    sources = collections.OrderedDict()
    sources['STEP1A2R_pre'] = {d: [p('STEP1A2R_20261124T164909Z/pre_pages/' + d)]
                               for d in os.listdir(p('STEP1A2R_20261124T164909Z/pre_pages'))}
    sources['LIVESIM_pre'] = {d: [p('LIVESIM_20261125T113851Z/collect/pre/' + d)]
                              for d in os.listdir(p('LIVESIM_20261125T113851Z/collect/pre'))}
    live = collections.defaultdict(list)
    croot = p('LIVESIM_20261125T113851Z/collect')
    for chunk in sorted(os.listdir(croot)):
        if chunk == 'pre':
            continue
        for d in os.listdir(os.path.join(croot, chunk)):
            live[d].append(os.path.join(croot, chunk, d))
    sources['LIVESIM_live'] = dict(live)

    page_schema, state_schema = None, None
    per = collections.defaultdict(dict)
    for sname, pools in sources.items():
        for pool, dirs in pools.items():
            txs, states, nonv = {}, [], 0
            for d in dirs:
                for f in sorted(os.listdir(d)):
                    fp = os.path.join(d, f)
                    if fp not in verified:
                        nonv += 1; continue      # never use unverified files
                    if f == 'STATE.json':
                        st = json.load(open(fp)); states.append(st)
                        state_schema = state_schema or schema(st)
                    elif f.startswith('page_'):
                        pg = json.load(gzip.open(fp))
                        page_schema = page_schema or schema(pg)
                        for t in pg.get('data') or []:
                            txs[t['transaction']['signatures'][0]] = t
            per[pool][sname] = (txs, states, nonv)

    rows, excluded = [], []
    tot = collections.Counter()
    for e in L['list']:
        pool = e['pool']
        if pool.startswith(PILOT_PREFIX):
            excluded.append({'pool': pool, 'reason': 'pilote G2-3'}); continue
        cfg = L['configs'].get(e['config'])
        fl = FL.get(pool)
        row = {'pool': pool, 'base_mint': e['base_mint'], 'quote_mint': WSOL, 'wsol_vault': e['wsol_vault'],
               'amm_config': e['config'],
               'trade_fee_rate': cfg['trade_fee_rate'] if cfg else ND,
               'trade_fee_rate_unit': 'per 1e6 (2500 = 0.25%)',
               'creator_fee_rate_config': cfg['creator_fee_rate'] if cfg else ND,
               'protocol_fee_rate': cfg['protocol_fee_rate'] if cfg else ND,
               'fund_fee_rate': cfg['fund_fee_rate'] if cfg else ND,
               'amm_config_index': cfg['index'] if cfg else ND,
               'creator_fee_flag': ({'enable_creator_fee': fl['enable_creator_fee'], 'creator_fee_on': fl['creator_fee_on'],
                                     'amm_config_in_flags_matches_L': fl['amm_config'] == e['config'],
                                     'source': 'CREATOR_FEE_FLAGS_20261125/FLAGS_LIST_L.json'} if fl else ND),
               'reserves': [{'quote_wsol_lamports': e['reserve_lamports'], 'base': ND, 'slot': L['t0_slot'],
                             'time': L['t0_time'], 'source': 'LIST_L.json reserve_lamports (WSOL vault at t0_slot)'}],
               'in_U2_selected': pool in u2sel,
               'creation': ND, 'sources': {}}
        if pool in u2sel and u2sel[pool].get('reserve_lamports') != e['reserve_lamports']:
            row['anomaly_U2_reserve_differs'] = True
        for sname in sources:
            if sname not in per.get(pool, {}):
                row['sources'][sname] = ND; continue
            txs, states, nonv = per[pool][sname]
            ok = [t for t in txs.values() if t['meta'].get('err') is None]
            n_sw, n_swtx, n_log, inits = 0, 0, 0, []
            bvault = collections.Counter()
            for t in ok:
                ks = keys_of(t)
                c = 0
                for disc, accs in cpmm_ixs(t, ks):
                    if disc in DISC and len(accs) > 3 and accs[3] == pool:
                        c += 1
                    if disc in INIT_DISC and pool in accs:
                        inits.append((t['slot'], t.get('blockTime'), t['transaction']['signatures'][0]))
                n_sw += c; n_swtx += c > 0
                st = []
                for l in t['meta'].get('logMessages') or []:
                    if l.startswith('Program ') and ' invoke [' in l:
                        st.append(l.split()[1])
                    elif l.startswith('Program ') and (l.endswith(' success') or ' failed' in l) and not l.startswith(('Program log', 'Program data')):
                        st and st.pop()
                    elif l.startswith('Program log: Instruction: Swap') and st and st[-1] == CPMM and pool in ks:
                        n_log += 1
                for b in t['meta'].get('postTokenBalances') or []:
                    if b['mint'] == e['base_mint'] and b.get('owner') == 'GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL':
                        bvault[ks[b['accountIndex']]] += 1
            bt = [t['blockTime'] for t in txs.values() if t.get('blockTime') is not None]
            src = {'n_transactions': len(txs), 'n_failed': len(txs) - len(ok),
                   'n_swaps': n_sw, 'n_swap_transactions': n_swtx, 'n_swap_log_instructions_cross_check': n_log,
                   'first_blockTime': min(bt) if bt else ND, 'last_blockTime': max(bt) if bt else ND,
                   'requested_windows': [s.get('window') for s in states] if states else ND,
                   'all_states_done': all(s.get('done') for s in states) if states else ND,
                   'state_transactions_sum': sum(s.get('transactions', 0) for s in states) if states else ND,
                   'n_chunks': len(states), 'unverified_files_skipped': nonv}
            if inits:
                i0 = min(inits)
                row['creation'] = {'slot': i0[0], 'blockTime': i0[1], 'signature': i0[2], 'source': sname}
            ordered = sorted(ok, key=lambda t: (t['slot'], t.get('transactionIndex', 0)))
            bv = bvault.most_common(1)[0][0] if bvault else None

            def bal(t, which, acct):
                ks = keys_of(t)
                for b in t['meta'].get(which) or []:
                    if ks[b['accountIndex']] == acct:
                        return int(b['uiTokenAmount']['amount'])
                return None
            if ordered:
                f, l = ordered[0], ordered[-1]
                for tag, t, which in (('start', f, 'preTokenBalances'), ('end', l, 'postTokenBalances')):
                    row['reserves'].append({'quote_wsol_lamports': bal(t, which, e['wsol_vault']),
                                            'base_atomic': bal(t, which, bv) if bv else ND, 'base_vault': bv or ND,
                                            'slot': t['slot'], 'time': t.get('blockTime'),
                                            'source': '%s %s of %s-of-source tx %s' % (sname, which, 'first' if tag == 'start' else 'last',
                                                                                      t['transaction']['signatures'][0]),
                                            'note': 'vault token balances (include unclaimed protocol/fund/creator fees); None = vault absent from that balance list'})
            row['sources'][sname] = src
            for k in ('n_transactions', 'n_failed', 'n_swaps'):
                tot[sname + '.' + k] += src[k]
            tot[sname + '.pools'] += 1
            tot[sname + '.pools_log_vs_ix_swap_differs'] += n_log != n_sw
        rows.append(row)
        tot['pools_with_creation'] += row['creation'] != ND
    with open(os.path.join(OUT, 'INVENTAIRE_CPMM_L.jsonl'), 'w') as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, separators=(',', ':')) + '\n')
    extra_pools = {s: sorted(set(v) - {e['pool'] for e in L['list']}) for s, v in sources.items()}
    excl_in_sources = {s: sorted(x for x in v if x.startswith(PILOT_PREFIX)) for s, v in sources.items()}
    meta.update(list_l={'total': len(L['list']), 'included': len(rows), 'excluded': excluded,
                        't0_slot': L['t0_slot'], 't0_time': L['t0_time']},
                counts=dict(tot), page_record_schema=page_schema, state_schema=state_schema,
                list_l_entry_fields=sorted(L['list'][0]), list_l_config_fields=sorted(next(iter(L['configs'].values()))),
                flags_entry_fields=sorted(next(iter(FL.values()))),
                source_pools_not_in_L=extra_pools, pilot_pools_present_in_sources_ignored=excl_in_sources,
                pools_per_source={s: len(v) for s, v in sources.items()})
    json.dump(meta, open(os.path.join(OUT, '.cpmm_meta_part.json'), 'w'), indent=1, sort_keys=True)
    print(json.dumps({k: (v['ok'], len(v['mismatched']), len(v['missing'])) for k, v in meta['sums_verification'].items()}))
    print(json.dumps(meta['counts'])); print(meta['cross_checks']); print(len(uncovered), uncovered[:5]); print(extra_pools)
    print(excl_in_sources)


main()
