"""Offline accounting of all retained mint-history bodies; never relaxes a guard."""
import argparse
import json
from pathlib import Path
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1])
parser.add_argument('--result',type=Path)
parser.add_argument('--bundle',type=Path)
args=parser.parse_args()
REPO=args.repo.resolve()
sys.dont_write_bytecode=True
sys.path.insert(0,str(REPO))
from bot.p3.evidence import verify_bundle

MINT='BNbNtWCfULYXXDNbm4VanecLox1geFsgKbWooke8iTFm'
TOKEN='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
result=json.loads((args.result or REPO/'validation/P3_MINT_HISTORY_006.json').read_text())
if result['plan_sha256']!='ad170961e06d9199119da1b3a6ae1d7abc3c5c35cc71b10469d101475a70c0a8':
    raise ValueError('Result is outside the fixed preregistered control006 scope')
plan={'creation_slot':461979373,'first_snapshot_slot':461982938,
      'creation_signature':'3umbNJxM9hFM6GAebVd6pj86q7Hj5ete5ygjVE6BcPpr73XWQQPQ5Ron5Nv9tw94XJdmoBBirs1d8fNFwVU4mADa',
      'creation_transaction_index':50,'target_supply_deficit_atomic':'979542505800'}
anchors=[('launchlab_002','8932cf725770daba7a9deddd12d0e29805c1ed1eae22bc57d18fb1d001eb8790'),
         ('mint_history_004','4f115ac378f61427ad26f41a6da25675a43e9c4fc739aab7990edcb9eec7fbc2'),
         ('mint_history_005','1c1812f6f41acc37a6d0a3e66ba4a335ef2666667bf4ab670c5afc443b1bdcce')]
bundles=[verify_bundle(REPO/'evidence/p3'/name,expected_tail=tail) for name,tail in anchors]
bundles.append(verify_bundle(args.bundle or REPO/'evidence/p3/mint_history_006',expected_tail=result['tail_hash']))
page=next(e['payload']['raw_signature_page'] for e in bundles[1]['events'] if 'raw_signature_page' in e['payload'])
transactions={}
for bundle in bundles:
    for e in bundle['events']:
        tx=e['payload'].get('raw_transaction')
        if not isinstance(tx,dict) or e['signature'] is None:
            continue
        slot=tx.get('slot')
        if not isinstance(slot,int) or not plan['creation_slot']<=slot<=plan['first_snapshot_slot']:
            continue
        if e['signature'] in transactions:
            assert transactions[e['signature']]==tx
        transactions[e['signature']]=tx
eligible={r['signature'] for r in page if r['err'] is None and plan['creation_slot']<=r['slot']<=plan['first_snapshot_slot']}
missing=sorted(eligible-set(transactions))
checks=[]
for signature in sorted(eligible & set(transactions),key=lambda s:(transactions[s]['slot'],s)):
    tx=transactions[signature];meta=tx['meta'];message=tx['transaction']['message']
    assert meta['err'] is None and signature in tx['transaction']['signatures']
    instructions=list(message['instructions'])
    for group in meta.get('innerInstructions',[]):instructions.extend(group['instructions'])
    burns=[];minted=0;unparsed_token=0
    for i,instruction in enumerate(instructions):
        if instruction.get('programId')!=TOKEN:continue
        parsed=instruction.get('parsed')
        if not isinstance(parsed,dict):unparsed_token+=1;continue
        kind,info=parsed.get('type'),parsed.get('info',{})
        if info.get('mint')!=MINT:continue
        if kind in ('burn','burnChecked'):
            value=info['amount'] if kind=='burn' else info['tokenAmount']['amount']
            assert type(value) is str and value.isascii() and value.isdecimal()
            burns.append({'instruction_index':i,'type':kind,'amount_atomic':str(int(value)),
                          'source_token_account':info['account']})
        elif kind in ('mintTo','mintToChecked'):
            value=info['amount'] if kind=='mintTo' else info['tokenAmount']['amount']
            minted+=int(value)
    pre=sum(int(b['uiTokenAmount']['amount']) for b in meta.get('preTokenBalances',[]) if b['mint']==MINT)
    post=sum(int(b['uiTokenAmount']['amount']) for b in meta.get('postTokenBalances',[]) if b['mint']==MINT)
    parsed_burn=sum(int(b['amount_atomic']) for b in burns)
    balance_loss=pre-post
    accounted=balance_loss==parsed_burn-minted
    same_slot_order=None
    if tx['slot']==plan['creation_slot']:
        tx_index=tx.get('transactionIndex')
        same_slot_order=(tx_index>plan['creation_transaction_index']) if type(tx_index) is int else None
    checks.append({'signature':signature,'slot':tx['slot'],'transaction_index':tx.get('transactionIndex'),
        'original_creation':signature==plan['creation_signature'],
        'after_creation_within_same_slot':same_slot_order,'burns':burns,
        'minted_atomic':str(minted),'parsed_burn_sum_atomic':str(parsed_burn),
        'sum_pre_affected_mint_account_balances_atomic':str(pre),
        'sum_post_affected_mint_account_balances_atomic':str(post),
        'independent_account_balance_loss_atomic':str(balance_loss),
        'account_balance_loss_equals_burns_minus_mints':accounted,
        'unparsed_token_instructions':unparsed_token})
noncreation=[c for c in checks if not c['original_creation']]
total=sum(int(c['parsed_burn_sum_atomic']) for c in noncreation)
independent=sum(int(c['independent_account_balance_loss_atomic'])+int(c['minted_atomic']) for c in noncreation)
target=int(plan['target_supply_deficit_atomic'])
order_safe=all(c['slot']>plan['creation_slot'] or not c['burns'] or c['after_creation_within_same_slot'] is True for c in noncreation)
report={'schema':'p3-history-006-offline-burn-reconciliation-v1','plan_sha256':result['plan_sha256'],
    'tail_hash_006':result['tail_hash'],'known_page_eligible_transactions':len(eligible),
    'retained_eligible_transaction_bodies':len(checks),'known_page_missing_bodies':missing,
    'burn_instruction_count':sum(len(c['burns']) for c in noncreation),'checks':checks,
    'all_integer_balance_crosschecks_match':all(c['account_balance_loss_equals_burns_minus_mints'] for c in checks),
    'post_creation_minted_atomic':str(sum(int(c['minted_atomic']) for c in noncreation)),
    'parsed_post_creation_burn_sum_atomic':str(total),
    'independent_affected_accounts_balance_loss_atomic':str(independent),
    'target_supply_deficit_atomic':str(target),'unexplained_deficit_atomic':str(target-total),
    'same_slot_burn_order_safe':order_safe,
    'retained_observations_arithmetically_reconcile_supply':total==target and independent==target and order_safe and not missing,
    'independent_provider_history_exhaustiveness_certified':False,
    'risk_guards_changed':False,'new_network_requests':0,'economic_verdict':'INSUFFICIENT DATA'}
print(json.dumps(report,indent=2,sort_keys=True))
