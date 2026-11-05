"""Offline independent burn/account-balance cross-check; no network access."""
import json
from pathlib import Path
import sys

REPO=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO))
from bot.p3.evidence import verify_bundle

result=json.loads((REPO/'validation/P3_MINT_HISTORY_005.json').read_text())
bundle=verify_bundle(REPO/'evidence/p3/mint_history_005',expected_tail=result['tail_hash'])
checks=[]
for e in bundle['events']:
    tx=e['payload'].get('raw_transaction')
    if not isinstance(tx,dict):continue
    message=tx['transaction']['message'];meta=tx['meta']
    instructions=list(message['instructions'])
    for group in meta.get('innerInstructions',[]):instructions.extend(group['instructions'])
    burns=[i for i in instructions if i.get('programId')=='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
           and isinstance(i.get('parsed'),dict) and i['parsed'].get('type') in ('burn','burnChecked')]
    if not burns:continue
    assert meta['err'] is None
    keys=[k['pubkey'] if isinstance(k,dict) else k for k in message['accountKeys']]
    # The two observed transactions each have a single SPL token mutation: burn.
    token_instructions=[i for i in instructions if i.get('programId')=='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA']
    assert len(token_instructions)==len(burns)==1
    info=burns[0]['parsed']['info'];source=info['account'];mint=info['mint']
    account_index=keys.index(source)
    pre=next(b for b in meta['preTokenBalances'] if b['accountIndex']==account_index and b['mint']==mint)
    post=next(b for b in meta['postTokenBalances'] if b['accountIndex']==account_index and b['mint']==mint)
    before,after=int(pre['uiTokenAmount']['amount']),int(post['uiTokenAmount']['amount'])
    parsed_amount=int(info['tokenAmount']['amount'])
    assert before-after==parsed_amount
    checks.append({'signature':e['signature'],'slot':e['source_slot'],'mint':mint,
        'source_token_account':source,'pre_balance_atomic':str(before),'post_balance_atomic':str(after),
        'independent_account_balance_drop_atomic':str(before-after),
        'parsed_burn_atomic':str(parsed_amount),'single_SPL_token_mutation':True,
        'balance_drop_equals_parsed_burn':True})
assert len(checks)==2
observed=sum(int(c['independent_account_balance_drop_atomic']) for c in checks)
assert observed==int(result['observed_burn_sum_atomic'])
target=int(result['target_supply_deficit_atomic'])
report={'schema':'p3-history-005-independent-burn-qualification-v1','tail_hash':result['tail_hash'],
    'checks':checks,'independently_confirmed_burn_sum_atomic':str(observed),
    'target_supply_deficit_atomic':str(target),'unexplained_deficit_atomic':str(target-observed),
    'burn_mechanism_observed':True,'full_supply_reconciliation':False,
    'new_network_requests':0,'risk_guards_changed':False,'economic_verdict':'INSUFFICIENT DATA',
    'history_still_missing':'21 other eligible transactions from control004 plus one same-creation-slot transaction excluded by its strict lower boundary; no completeness guarantee from one RPC signature page'}
print(json.dumps(report,indent=2,sort_keys=True))
