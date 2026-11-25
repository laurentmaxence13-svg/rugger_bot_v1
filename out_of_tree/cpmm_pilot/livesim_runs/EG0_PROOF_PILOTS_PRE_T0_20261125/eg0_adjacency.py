"""E-G0 PROOF, DIAGNOSTIC ONLY (R02 (b), R04 12:00Z): on anchored pre-T0 pages, is every reserves break adjacent to an
undecoded transaction? Causes of the non-decoding (by transaction version); can the missing swap be recovered from the
transaction meta (vault token balances)? No position, no P&L, no window datum; frozen decoder (cpmmx) and cpmmcost 0.3.1."""
import collections, json, sys
from pathlib import Path
from cpmmcost import model as CC
from cpmmpilot.store import read_gz_page
from cpmmx import timeline as TL
LL, OUT, ROOT = sys.argv[1], sys.argv[2], Path(sys.argv[3])
POOLS = sys.argv[4:]
ll = json.loads(Path(LL).read_text()); rows = {r['pool']: r for r in ll['list']}
res = {}
for pool in POOLS:
    txs = {}
    for page in sorted((ROOT / pool).glob('page_*.json.gz')):
        for tx in read_gz_page(page).get('data') or []:
            txs[tx['transaction']['signatures'][0]] = tx
    line = TL.build(pool, txs, base_mint=rows[pool]['base_mint'])
    cfg = dict(ll['configs'][rows[pool]['config']], slot=ll['t0_slot']); cfg['sha256'] = cfg['raw_sha256']
    fees = CC.fees_from_amm_config(cfg)
    breaks = [b for b in TL.continuity(line, fees.protocol_fee_rate, fees.fund_fee_rate) if b['reason'] != 'lp_change_between']
    skipped = {sig: why for sig, why in line.skipped}
    spos = sorted(((txs[s].get('slot'), txs[s].get('transactionIndex')), s) for s in skipped)
    def between(lo, hi):
        return [s for p, s in spos if lo < p < hi]
    adjacent, lonely = 0, []
    used = set()
    for b in breaks:
        a, c = line.swaps[b['index']], line.swaps[b['index'] + 1]
        got = between((a.slot, a.tx_index), (c.slot, c.tx_index))
        if got:
            adjacent += 1; used.update(got)
        else:
            lonely.append(dict(index=b['index'], slot=a.slot, next_slot=c.slot))
    wsol_vault = rows[pool]['wsol_vault']
    def recoverable(tx):
        keys = tx['transaction']['message'].get('accountKeys') or []
        keys = [k if isinstance(k, str) else k.get('pubkey') for k in keys]
        loaded = tx.get('meta', {}).get('loadedAddresses') or {}
        keys += (loaded.get('writable') or []) + (loaded.get('readonly') or [])
        pre = {b['accountIndex']: b for b in tx.get('meta', {}).get('preTokenBalances') or []}
        post = {b['accountIndex']: b for b in tx.get('meta', {}).get('postTokenBalances') or []}
        if wsol_vault not in keys:
            return 'wsol_vault_absent'
        i = keys.index(wsol_vault)
        if i not in pre or i not in post:
            return 'no_vault_token_balance'
        return 'vault_balances_present'
    reasons = collections.Counter(skipped.values())
    versions = collections.Counter(str(txs[s].get('version')) for s in skipped)
    failed = sum(1 for s in skipped if (txs[s].get('meta') or {}).get('err') is not None)
    recov = collections.Counter(recoverable(txs[s]) for s in skipped)
    res[pool] = dict(swaps=len(line.swaps), skipped=len(skipped), skipped_reasons=dict(reasons),
                     skipped_versions=dict(versions), all_versions=dict(collections.Counter(str(t.get('version')) for t in txs.values())),
                     skipped_failed_tx=failed, breaks=len(breaks), breaks_adjacent_to_undecoded=adjacent,
                     breaks_not_adjacent=lonely[:20], breaks_not_adjacent_count=len(lonely),
                     undecoded_adjacent_to_a_break=len(used), undecoded_not_adjacent=len(skipped) - len(used),
                     undecoded_share_of_pool_tx=len(skipped) / max(1, len(txs)),
                     recovery_from_vault_balances=dict(recov))
    print(pool[:6], json.dumps({k: v for k, v in res[pool].items() if k != 'breaks_not_adjacent'}))
Path(OUT).write_text(json.dumps(res, indent=1, sort_keys=True) + '\n')
