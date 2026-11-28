"""Offline inventory of the W1 LaunchLab exploratory export (inventory only: no price/return/PnL)."""
import base64, collections, gzip, hashlib, json, os, struct, sys

ROOT = sys.argv[1]
OUT = sys.argv[2]
ANCHOR = 'ebe1959dc57ca6b6a1442aafb808b5ac8cbf7281f3508ca08cd42cc40ba3c41e'
SUMS_EXPECTED_PREFIX = '7e9e7cdb'
FORBIDDEN = ('p0/', 'P0_SCELLE', '9f19ccac', 'sauvegarde_20261110')
LL = 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'
AUTH = 'WLHv2UAZm6z4KyaaELi5pjdbJh6RESMva1Rnn8pJVVh'
WSOL = 'So11111111111111111111111111111111111111112'
EVENT_IX_TAG = bytes.fromhex('e445a52e51cb9a1d')
TRADE_DISC = hashlib.sha256(b'event:TradeEvent').digest()[:8]
TRADE_SIZE = 8 + 32 + 13 * 8 + 3
U64 = ('total_base_sell', 'virtual_base', 'virtual_quote', 'real_base_before', 'real_quote_before',
       'real_base_after', 'real_quote_after', 'amount_in', 'amount_out', 'protocol_fee',
       'platform_fee', 'creator_fee', 'share_fee')
SWAP_IX = ('BuyExactIn', 'BuyExactOut', 'SellExactIn', 'SellExactOut')
INIT_IX = ('Initialize', 'InitializeV2', 'InitializeWithToken2022')
B58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
IDX = {c: i for i, c in enumerate(B58)}
ND = 'non disponible'


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


def b58e(raw):
    n = int.from_bytes(raw, 'big'); o = ''
    while n:
        n, r = divmod(n, 58); o = B58[r] + o
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + o


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


def trade_events(tx, keys):
    evs = []
    for grp in tx['meta'].get('innerInstructions') or []:
        for ix in grp['instructions']:
            pid = keys[ix['programIdIndex']] if 'programIdIndex' in ix else ix.get('programId')
            if pid != LL or not isinstance(ix.get('data'), str):
                continue
            try:
                raw = b58d(ix['data'])
            except KeyError:
                continue
            if raw[:8] != EVENT_IX_TAG:
                continue
            p = raw[8:]
            if len(p) != TRADE_SIZE or p[:8] != TRADE_DISC:
                continue
            v = dict(zip(U64, struct.unpack_from('<13Q', p, 40)))
            v['pool'] = b58e(p[8:40]); v['side'] = 'buy' if p[144] == 0 else 'sell'
            evs.append(v)
    return evs


def ll_instructions(logs):
    st, out = [], []
    for l in logs or []:
        if l.startswith('Program ') and ' invoke [' in l:
            st.append(l.split()[1])
        elif l.startswith('Program ') and (l.endswith(' success') or ' failed' in l) and len(l.split()) >= 3 and not l.startswith('Program log') and not l.startswith('Program data'):
            if st: st.pop()
        elif l.startswith('Program log: Instruction: ') and st and st[-1] == LL:
            out.append(l[len('Program log: Instruction: '):].strip())
    return out


def schema(o, depth=0):
    if isinstance(o, dict):
        return {k: schema(v, depth + 1) for k, v in o.items()}
    if isinstance(o, list):
        return [schema(o[0], depth + 1)] if o else []
    return type(o).__name__


def main():
    mp = os.path.join(ROOT, 'pools', 'MANIFEST.json')
    sp = os.path.join(ROOT, 'SHA256SUMS_PRELIMINAIRE.json')
    man_sha, sums_sha = sha(mp), sha(sp)
    sums = json.load(open(sp))['outputs']
    meta = {'anchor': {'file': 'pools/MANIFEST.json', 'sha256': man_sha, 'expected': ANCHOR, 'ok': man_sha == ANCHOR,
                       'listed_in_SHA256SUMS_PRELIMINAIRE': sums.get('pools/MANIFEST.json') == man_sha},
            'SHA256SUMS_PRELIMINAIRE.json': {'sha256': sums_sha, 'expected_prefix': SUMS_EXPECTED_PREFIX,
                                             'ok': sums_sha.startswith(SUMS_EXPECTED_PREFIX)}}
    if man_sha != ANCHOR:
        raise SystemExit('anchor mismatch')
    man = json.load(open(mp))
    ver = {'ok': 0, 'mismatch': [], 'missing': [], 'sums_cross_check_disagree': []}
    rows = []
    tot = collections.Counter()
    page_schema = None
    gmax = (0, None, None)
    for ent in man['pools']:
        fp = os.path.join(ROOT, 'pools', guard(ent['file']))
        if not os.path.exists(fp):
            ver['missing'].append(ent['file']); continue
        h = sha(fp)
        if h != ent['sha256']:
            ver['mismatch'].append(ent['file']); continue
        ver['ok'] += 1
        s2 = sums.get('pools/' + ent['file'])
        if s2 is not None and s2 != h:
            ver['sums_cross_check_disagree'].append(ent['file'])
        d = json.load(gzip.open(fp))
        pool = ent['pool']
        if page_schema is None:
            page_schema = schema(d)
        sigs = d['signatures']; txs = d['transactions']
        failed = [s for s in sigs if s.get('err') is not None]
        for s_ in sigs:
            if s_['slot'] > gmax[0]:
                gmax = (s_['slot'], s_.get('blockTime'), pool)
        ok_sigs = {s['signature'] for s in sigs if s.get('err') is None}
        bt_s = [s['blockTime'] for s in sigs if s.get('blockTime') is not None]
        bt_t = [t['blockTime'] for t in txs.values() if t.get('blockTime') is not None]
        missing_bodies = sorted(ok_sigs - set(txs))
        bodies_not_listed = sorted(set(txs) - {s['signature'] for s in sigs})
        evs, log_swaps, swap_tx, creation, migration = [], 0, 0, [], []
        failed_bodies = 0
        vault_base_mints, vault_addr = collections.Counter(), collections.Counter()
        for sig, t in txs.items():
            if t['meta'].get('err') is not None:
                failed_bodies += 1; continue
            ks = keys_of(t)
            if pool not in ks:
                continue
            ins = ll_instructions(t['meta'].get('logMessages'))
            ev = [e for e in trade_events(t, ks) if e['pool'] == pool]
            log_swaps += sum(1 for i in ins if i in SWAP_IX)
            if ev:
                swap_tx += 1
            for i, e in enumerate(ev):
                e['_k'] = (t['slot'], t.get('transactionIndex', 0), i); e['_bt'] = t.get('blockTime'); e['_sig'] = sig
                evs.append(e)
            if any(i in INIT_IX for i in ins):
                creation.append((t['slot'], t.get('blockTime'), sig, [i for i in ins if i in INIT_IX][0]))
            if 'MigrateToCpswap' in ins:
                migration.append((t['slot'], t.get('blockTime'), sig))
            for b in t['meta'].get('postTokenBalances') or []:
                if b.get('owner') == AUTH:
                    vault_addr[(ks[b['accountIndex']], b['mint'])] += 1
                    if b['mint'] != WSOL:
                        vault_base_mints[b['mint']] += 1
        evs.sort(key=lambda e: e['_k'])
        breaks = sum(1 for a, b in zip(evs, evs[1:])
                     if (a['real_base_after'], a['real_quote_after']) != (b['real_base_before'], b['real_quote_before']))
        base_mint = vault_base_mints.most_common(1)[0][0] if vault_base_mints else ND
        # this pool's vaults = most frequent authority-owned accounts for base mint and WSOL
        bv = max((k for k in vault_addr if k[1] == base_mint), key=lambda k: vault_addr[k], default=None)
        qv = max((k for k in vault_addr if k[1] == WSOL), key=lambda k: vault_addr[k], default=None)

        def vault_bal(t, which, acct):
            ks = keys_of(t)
            for b in t['meta'].get(which) or []:
                if ks[b['accountIndex']] == acct:
                    return int(b['uiTokenAmount']['amount'])
            return None
        ordered = sorted((t for t in txs.values() if t['meta'].get('err') is None and pool in keys_of(t)),
                         key=lambda t: (t['slot'], t.get('transactionIndex', 0)))
        vaults = ND
        if ordered and bv and qv:
            f, l = ordered[0], ordered[-1]
            vaults = {'base_vault': bv[0], 'quote_vault_wsol': qv[0],
                      'start': {'slot': f['slot'], 'blockTime': f.get('blockTime'), 'signature': f['transaction']['signatures'][0],
                                'base_vault_amount_pre': vault_bal(f, 'preTokenBalances', bv[0]),
                                'quote_vault_amount_pre': vault_bal(f, 'preTokenBalances', qv[0])},
                      'end': {'slot': l['slot'], 'blockTime': l.get('blockTime'), 'signature': l['transaction']['signatures'][0],
                              'base_vault_amount_post': vault_bal(l, 'postTokenBalances', bv[0]),
                              'quote_vault_amount_post': vault_bal(l, 'postTokenBalances', qv[0])},
                      'unit': 'atomic token units (raw amount string of uiTokenAmount); None = account absent from that balance list'}
        if evs:
            e0, e1 = evs[0], evs[-1]
            curve = {'source': 'LaunchLab TradeEvent (emit_cpi inner instruction) of first/last swap',
                     'start': {'slot': e0['_k'][0], 'blockTime': e0['_bt'], 'signature': e0['_sig'],
                               'real_base_before': e0['real_base_before'], 'real_quote_before': e0['real_quote_before'],
                               'virtual_base': e0['virtual_base'], 'virtual_quote': e0['virtual_quote'],
                               'total_base_sell': e0['total_base_sell']},
                     'end': {'slot': e1['_k'][0], 'blockTime': e1['_bt'], 'signature': e1['_sig'],
                             'real_base_after': e1['real_base_after'], 'real_quote_after': e1['real_quote_after'],
                             'virtual_base': e1['virtual_base'], 'virtual_quote': e1['virtual_quote'],
                             'total_base_sell': e1['total_base_sell']},
                     'unit': 'atomic units (base token / lamports)'}
        else:
            curve = ND
        cr = min(creation) if creation else None
        row = {'pool': pool, 'base_mint': base_mint, 'quote_mint': ent.get('quote_mint'),
               'n_signatures': len(sigs), 'n_failed_signatures': len(failed), 'n_success_signatures': len(ok_sigs),
               'n_transaction_bodies': len(txs), 'n_failed_bodies': failed_bodies,
               'n_swaps_tradeevent': len(evs), 'n_swap_transactions': swap_tx, 'n_swaps_log_instructions': log_swaps,
               'n_buy': sum(1 for e in evs if e['side'] == 'buy'), 'n_sell': sum(1 for e in evs if e['side'] == 'sell'),
               'first_blockTime_signatures': min(bt_s) if bt_s else ND, 'last_blockTime_signatures': max(bt_s) if bt_s else ND,
               'first_blockTime_bodies': min(bt_t) if bt_t else ND, 'last_blockTime_bodies': max(bt_t) if bt_t else ND,
               'first_slot_manifest': ent['first_slot'], 'last_slot_manifest': ent['last_slot'],
               'active_near_window_end': ent['active_near_window_end'],
               'coverage_gaps': {'recorded_in_data': {'signatures_complete': d.get('signatures_complete')},
                                 'derived': {'success_signatures_without_body': len(missing_bodies),
                                             'bodies_not_in_signature_list': len(bodies_not_listed),
                                             'reserve_chain_breaks_between_consecutive_tradeevents': breaks},
                                 'explicit_gap_intervals': ND},
               'reserves_curve_tradeevent': curve, 'reserves_vault_token_balances': vaults,
               'creation': ({'slot': cr[0], 'blockTime': cr[1], 'signature': cr[2], 'instruction': cr[3]} if cr else ND),
               'migration_to_cpswap': ({'slot': min(migration)[0], 'blockTime': min(migration)[1], 'signature': min(migration)[2]} if migration else ND),
               'manifest_signatures': ent['signatures'], 'manifest_transactions': ent['transactions'],
               'file': 'pools/' + ent['file'], 'file_sha256': h}
        rows.append(row)
        for k in ('n_signatures', 'n_failed_signatures', 'n_transaction_bodies', 'n_swaps_tradeevent', 'n_swap_transactions',
                  'n_swaps_log_instructions', 'n_failed_bodies'):
            tot[k] += row[k]
        tot['pools_with_creation'] += cr is not None
        tot['pools_with_migration'] += bool(migration)
        tot['pools_signatures_complete_false'] += d.get('signatures_complete') is not True
        tot['pools_with_chain_breaks'] += breaks > 0
        tot['pools_without_swaps'] += not evs
        tot['pools_base_mint_nd'] += base_mint == ND
        tot['pools_log_vs_event_swap_count_differs'] += log_swaps != len(evs)
        tot['success_signatures_without_body'] += len(missing_bodies)
        tot['manifest_count_disagree'] += (ent['signatures'] != len(sigs) or ent['transactions'] != len(txs))
    wmax = man['source']['window']['slot_max']
    assert wmax == man['window_slot_max'] and gmax[0] <= wmax
    for r in rows:
        r['collection_end_unix'] = gmax[1]
        r['collection_end_slot'] = wmax
        r['collection_end_basis'] = 'global'
    json.dump({r['pool']: gmax[1] for r in rows}, open(os.path.join(OUT, 'INVENTAIRE_W1_COLLECTION_END.json'), 'w'),
              indent=0, sort_keys=True)
    meta['collection_end'] = {
        'scope': 'global (identical for all 2273 pools)',
        'collection_end_slot': wmax,
        'slot_source_fields': ['pools/MANIFEST.json: source.window.slot_max', 'pools/MANIFEST.json: window_slot_max'],
        'collection_end_unix': gmax[1],
        'unix_derivation': 'the export records no blockTime for slot_max; collection_end_unix = blockTime of the highest-slot '
                           'signature present in the whole export (slot %d, pool %s), i.e. %d slots below slot_max: a lower bound '
                           'of the true horizon, which lies at most ~%d slots (~%ds at ~0.4 s/slot) later' % (
                               gmax[0], gmax[2], wmax - gmax[0], wmax - gmax[0], round((wmax - gmax[0]) * 0.4)),
        'why_global': 'MANIFEST.contents: per-pool archives rebuilt from ONE LaunchLab program-window backfill '
                      '(source.window.address=LaunchLab program, slot_min..slot_max); every pool file has '
                      'signatures_complete=true; no per-pool cursor/until field exists in pool files '
                      '(fields: account, pool, signatures, signatures_complete, transactions, version). '
                      'Per-pool last_slot (MANIFEST) is the last event, not the horizon.',
        'related_not_horizon': {'entry_cutoff_slot': man.get('entry_cutoff_slot'),
                                'entry_cutoff_gap_slots': man.get('entry_cutoff_gap_slots'),
                                'note': 'entry cutoff = slot_max - gap, a research entry cutoff, not the collection end'},
        'per_pool_file': 'INVENTAIRE_W1_COLLECTION_END.json'}
    with open(os.path.join(OUT, 'INVENTAIRE_W1.jsonl'), 'w') as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True, separators=(',', ':')) + '\n')
    meta.update(verification_manifest_files={'listed': len(man['pools']), 'ok': ver['ok'], 'mismatched': len(ver['mismatch']),
                                             'missing': len(ver['missing']), 'mismatch_list': ver['mismatch'],
                                             'missing_list': ver['missing'],
                                             'SHA256SUMS_PRELIMINAIRE_cross_check_disagree': ver['sums_cross_check_disagree']},
                counts=dict(tot, pools=len(rows)), pool_record_schema=page_schema,
                manifest_top_level_fields=sorted(man), manifest_pool_entry_fields=sorted(man['pools'][0]),
                manifest_skipped_pools=len(man.get('skipped') or {}),
                manifest_skipped_by_reason_prefix=dict(collections.Counter(v.split(':')[0] for v in (man.get('skipped') or {}).values())),
                manifest_source_window=man.get('source', {}).get('window'), manifest_schema=man.get('schema'))
    json.dump(meta, open(os.path.join(OUT, '.w1_meta_part.json'), 'w'), indent=1, sort_keys=True)
    print(json.dumps(meta['verification_manifest_files'])); print(json.dumps(meta['counts']))
    print(meta['anchor'], meta['SHA256SUMS_PRELIMINAIRE.json'])


main()
