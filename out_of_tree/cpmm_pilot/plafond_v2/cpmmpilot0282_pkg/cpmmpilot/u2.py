"""U-2 of the CPMM pilot, exactly as owner text B(b) of R02 v1.2 and method U-2 v0.2.1 (D-a..D-c):
getSlot; getProgramAccounts AmmConfig (trade_fee_rate = 2 500, PDA checked); getProgramAccounts pools of each config with
WSOL as token_0 then token_1 (dataSlice 0..413); exclusions (status & 4, lp_supply = 0 -- technical eligibility, counted; anchored P0 visible / W1
lists; Token-2022 stays in L, U-4 is applied by cpmmcost.pool_gate at step 1); getMultipleAccounts of the WSOL vaults (PDA checked) -> reserve >= 100 SOL at T0 -> list L, hashed; permutation
seeded by int(sha_L[:8], 16); creation transaction by GTFA (asc, limit 1, full) in that order until 24 valid pools
(age >= 7 days, CPMM initialize at depth 1, no LaunchLab anywhere); < 20 valid after L is exhausted = INCONCLUSIF.
GTFA refused = STOP (no fallback). A truncated answer = STOP."""
import hashlib
import random

from cpmmx.events import CPMM_PROGRAM

from . import layout as L
from .rpc import MAX_TX_VERSION, MethodRefused, RpcError, canonical, sha
from .store import file_sha, read_json, write_gz_page, write_json

LAUNCHLAB_PROGRAM = 'LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj'     # bot.market.launchlab_events (frozen tree)
MIN_RESERVE_LAMPORTS = 100 * 10 ** 9
MIN_AGE_S = 7 * 86_400
TARGET, FLOOR = 24, 20
SCHEMA = 'cpmmpilot-u2-v0.1'


class U2Stop(RuntimeError):
    pass


def _value(result):
    return result['value'] if isinstance(result, dict) and 'value' in result else result


def snapshot(client, out, *, exclude=frozenset()):
    """Steps T0 + B + C: returns (list L, counts, t0_slot)."""
    t0_slot = client.call('getSlot', [{'commitment': 'finalized'}])
    raw_dir = out / 'raw'
    try:
        configs = client.call('getProgramAccounts', [CPMM_PROGRAM, dict(
            encoding='base64', withContext=True, filters=L.config_filters())])
    except RpcError as exc:
        raise U2Stop('program_accounts_failed:%s' % exc) from exc
    write_gz_page(raw_dir / 'gpa_configs.json.gz', configs)
    counts = dict(configs_seen=0, configs_u1=0, pools_seen=0, excluded_status=0, excluded_lp_zero=0,
                  excluded_anchored_lists=0, excluded_vault_pda=0, below_100_sol=0, list_l=0)
    keep_configs = []
    for row in _value(configs):
        counts['configs_seen'] += 1
        raw_bytes = L.raw(row['account']['data'])
        c = dict(L.decode_config(raw_bytes), raw_sha256=hashlib.sha256(raw_bytes).hexdigest())
        if c['trade_fee_rate'] != L.TRADE_FEE_RATE_U1 or L.config_pda(c['index']) != row['pubkey']:
            continue
        counts['configs_u1'] += 1
        keep_configs.append((row['pubkey'], c))
    candidates = {}
    for address, c in keep_configs:
        for side, offset in enumerate(L.MINT_OFFSETS):
            try:
                pools = client.call('getProgramAccounts', [CPMM_PROGRAM, dict(
                    encoding='base64', withContext=True, dataSlice=dict(offset=0, length=L.POOL_SLICE[1]),
                    filters=L.pool_filters(address, offset))])
            except RpcError as exc:
                raise U2Stop('program_accounts_failed:%s' % exc) from exc
            write_gz_page(raw_dir / ('gpa_pools_%s_%d.json.gz' % (address, offset)), pools)
            for row in _value(pools):
                counts['pools_seen'] += 1
                p = L.decode_pool(L.raw(row['account']['data']))
                pool = row['pubkey']
                if p['status'] & 4:
                    counts['excluded_status'] += 1
                elif p['lp_supply'] == 0:
                    counts['excluded_lp_zero'] += 1
                elif pool in exclude:
                    counts['excluded_anchored_lists'] += 1
                else:
                    wsol_vault = p['token_0_vault'] if side == 0 else p['token_1_vault']
                    base_mint = p['token_1_mint'] if side == 0 else p['token_0_mint']
                    candidates[pool] = dict(pool=pool, config=address, config_fields=c, wsol_vault=wsol_vault,
                                            base_mint=base_mint, wsol_side=side)
    pools = sorted(candidates)
    for start in range(0, len(pools), 100):
        batch = pools[start:start + 100]
        vaults = client.call('getMultipleAccounts', [[candidates[p]['wsol_vault'] for p in batch],
                                                    dict(encoding='base64')])
        write_gz_page(raw_dir / ('vaults_%05d.json.gz' % start), vaults)
        for pool, account in zip(batch, _value(vaults)):
            rec = candidates[pool]
            if account is None or L.vault_pda(pool, L.WSOL) != rec['wsol_vault']:
                counts['excluded_vault_pda'] += 1
                rec['drop'] = True
                continue
            mint, amount = L.spl_amount(L.raw(account['data']))
            if mint != L.WSOL or amount < MIN_RESERVE_LAMPORTS:
                counts['below_100_sol'] += 1
                rec['drop'] = True
                continue
            rec['reserve_lamports'] = amount
    lst = [dict(pool=r['pool'], config=r['config'], base_mint=r['base_mint'], wsol_vault=r['wsol_vault'],
                reserve_lamports=r['reserve_lamports']) for p, r in sorted(candidates.items()) if not r.get('drop')]
    counts['list_l'] = len(lst)
    configs_doc = {a: c for a, c in keep_configs}
    return lst, counts, t0_slot, configs_doc


def permutation(lst, sha_l):
    order = [r['pool'] for r in lst]
    random.Random(int(sha_l[:8], 16)).shuffle(order)
    return order


def creation_check(tx, *, t0_time):
    """(valid, reason) from the OLDEST transaction of the pool (GTFA asc limit 1)."""
    if tx is None:
        return False, 'no_transaction'
    logs = (tx.get('meta') or {}).get('logMessages')
    if not logs:
        return False, 'no_logs'
    stack, init_depth = [], None
    for line in logs:
        parts = line.split(' ')
        if len(parts) == 4 and parts[0] == 'Program' and parts[2] == 'invoke':
            stack.append(parts[1])
        elif len(parts) >= 3 and parts[0] == 'Program' and (parts[2] == 'success' or parts[2].startswith('failed')):
            if stack:
                stack.pop()
        elif line.startswith('Program log: Instruction: Initialize') and stack and stack[-1] == CPMM_PROGRAM:
            init_depth = init_depth or len(stack)
        if LAUNCHLAB_PROGRAM in parts:
            return False, 'launchlab_in_creation_transaction'
    if init_depth is None:
        return False, 'oldest_transaction_is_not_the_initialize'
    if init_depth != 1:
        return False, 'initialize_not_at_depth_1'
    if type(tx.get('blockTime')) is not int or tx['blockTime'] > t0_time - MIN_AGE_S:
        return False, 'younger_than_7_days'
    return True, 'ok'


def qualify(client, out, lst, sha_l, *, t0_time):
    order = permutation(lst, sha_l)
    valid, tested, reasons = [], [], {}
    for pool in order:
        if len(valid) == TARGET:
            break
        try:
            page = client.call('getTransactionsForAddress', [pool, dict(
                transactionDetails='full', sortOrder='asc', limit=1, encoding='json',
                maxSupportedTransactionVersion=MAX_TX_VERSION)])
        except MethodRefused as exc:
            raise U2Stop('gtfa_refused_no_fallback:%s' % exc) from exc
        write_gz_page(out / 'raw' / ('creation_%s.json.gz' % pool), page)
        tx = (page.get('data') or [None])[0]
        ok, why = creation_check(tx, t0_time=t0_time)
        tested.append(dict(pool=pool, valid=ok, reason=why))
        reasons[why] = reasons.get(why, 0) + 1
        if ok:
            valid.append(pool)
    verdict = 'INCONCLUSIF' if len(valid) < FLOOR else 'U2_OK'
    return dict(order_seed=int(sha_l[:8], 16), tested=len(tested), reasons=reasons, valid=valid, verdict=verdict,
                tested_rows=tested)


def run_list(client, out, *, t0_time, exclude=frozenset()):
    """U-2, FIRST time (owner text B: L is "hachée et ancrée par R02 ; puis" the permutation): getSlot, getProgramAccounts,
    WSOL vaults -> list L and its sha written, then STOP. No getTransactionsForAddress is ever sent here."""
    out.mkdir(parents=True, exist_ok=True)
    lst, counts, t0_slot, configs = snapshot(client, out, exclude=exclude)
    sha_l = sha(lst)
    write_json(out / 'LIST_L.json', dict(schema=SCHEMA, t0_slot=t0_slot, t0_time=t0_time, list=lst, sha256=sha_l,
                                         counts=counts, configs=configs))
    if len(lst) < FLOOR:
        doc = dict(schema=SCHEMA, verdict='INCONCLUSIF', reason='list_l_below_20', counts=counts, sha_l=sha_l)
        write_json(out / 'U2.json', doc)
        return doc
    return dict(schema=SCHEMA, verdict='LIST_L_AWAITS_R02_ANCHOR', t0_slot=t0_slot, t0_time=t0_time, counts=counts,
                sha_l=sha_l, list_l_file_sha256=file_sha(out / 'LIST_L.json'), budget=client.budget.snapshot())


def run_qualify(client, out, *, anchored_sha_l):
    """U-2, SECOND time, only with the sha of L anchored by R02: the file is re-read and re-hashed BEFORE any call."""
    doc = read_json(out / 'LIST_L.json')
    lst = doc['list']
    if sha(lst) != doc['sha256'] or doc['sha256'] != anchored_sha_l:
        raise U2Stop('list_l_not_anchored')
    if len(lst) < FLOOR:
        raise U2Stop('list_l_below_20_no_second_time')
    sha_l, configs, t0_time = doc['sha256'], doc['configs'], doc['t0_time']
    q = qualify(client, out, lst, sha_l, t0_time=t0_time)
    by_pool = {r['pool']: r for r in lst}
    selected = [dict(by_pool[p], amm_config=dict(configs[by_pool[p]['config']], address=by_pool[p]['config']))
                for p in q['valid']]
    out_doc = dict(schema=SCHEMA, t0_slot=doc['t0_slot'], t0_time=t0_time, counts=doc['counts'], sha_l=sha_l,
                   anchored_sha_l=anchored_sha_l, permutation_seed=q['order_seed'], tested=q['tested'],
                   creation_reasons=q['reasons'], verdict=q['verdict'], selected=selected,
                   budget=client.budget.snapshot())
    write_json(out / 'U2.json', out_doc)
    return out_doc


def run(client, out, *, t0_time, exclude=frozenset()):
    """Both times in a row: OFFLINE rehearsal and tests only (the rehearsal's own sha stands for R02's anchor)."""
    first = run_list(client, out, t0_time=t0_time, exclude=exclude)
    if first['verdict'] != 'LIST_L_AWAITS_R02_ANCHOR':
        return first
    return run_qualify(client, out, anchored_sha_l=first['sha_l'])


__all__ = ['run', 'run_list', 'run_qualify', 'snapshot', 'permutation', 'creation_check', 'qualify', 'U2Stop', 'canonical']
