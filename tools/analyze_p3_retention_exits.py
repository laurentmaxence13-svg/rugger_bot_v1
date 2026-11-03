"""Independent offline v3 exit diagnosis and invariant-based arithmetic oracle."""
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(repo))
from bot.p3.evidence import verify_bundle
from bot.p3.launchlab import _pool, observed_sell_projection, SnapshotEvidenceError

root = repo/'evidence/p3/retention_003'
# Anchor retained separately in the preregistered control's verified export.
anchor = '914901e885fa97c87e7e81f0bd2750d0092a4cfb7a12f709c5402c993ed75fce'
bundle = verify_bundle(root, expected_tail=anchor)
events = bundle['events']
by_id = {e['id']: e for e in events}
quotes = [e for e in events if e['kind'] == 'quote_attempt'
          and e['payload'].get('provider') == 'raydium_trade_api']
buys = {e['mint']: e for e in quotes if e['payload']['quote_side'] == 'buy'}
provider = []
for e in quotes:
    p = e['payload']
    body = p['retained_sanitized_response']
    raw = json.dumps(body, sort_keys=True, allow_nan=False)
    assert hashlib.sha256(raw.encode()).hexdigest() == p['sanitized_response_sha256']
    provider.append({'observation_id': e['id'], 'mint': e['mint'], 'side':p['quote_side'],
        'http_status':p['http_status'], 'normalized_outcome':p['outcome'],
        'provider_success':body['success'], 'provider_message':body.get('msg'),
        'body_digest_verified':True, 'input_amount_atomic':p['input_amount_atomic'],
        'output_amount_atomic':p['output_amount_atomic'],
        'source_time_ms':p['source_time_ms'], 'source_slot':p['source_slot']})
rows = []
for e in events:
    if e['kind'] != 'candidate_decision' or not isinstance(e['payload'].get('analysis'), dict):
        continue
    a = e['payload']['analysis']
    snapshot = by_id[e['payload']['snapshot_observation_id']]
    sp = snapshot['payload']
    accounts = dict(zip(sp['requested_addresses'], sp['raw_rpc_result']['value']))
    pool, _ = _pool(accounts[sp['addresses']['pool']])
    facts = a['facts']
    rates = tuple(int(value) for value in (facts['config']['trade_fee_rate_ppm'],
        facts['platform']['platform_fee_rate_ppm'], facts['platform']['creator_fee_rate_ppm']))
    vault = int(facts['quote_vault']['amount_atomic'])
    buy = buys[e['mint']]
    quantity = int(buy['payload']['output_amount_atomic'])
    try:
        actual = observed_sell_projection(pool, input_token_atomic=quantity, fee_rates_ppm=rates,
            quote_vault_lamports=vault, curve_type=int(facts['config']['curve_type']))
    except SnapshotEvidenceError as error:
        actual = {'outcome':'unavailable', 'reason':str(error), 'output_lamports':None}
    projection = a['conditional_projection']
    # Second method: preserve the x*y invariant and ceil the reserve left behind.
    # Production uses floor(input*x/(y+input)); no production fee/output helper is used here.
    x, y = pool['virtual_a']-pool['real_a'], pool['virtual_b']+pool['real_b']
    budget, denominator, rate = 10**9, 10**6, sum(rates)
    fee_in = math.ceil(Fraction(budget*rate, denominator))
    effective = budget-fee_in
    quote_after_buy = y+effective
    base_after_buy = math.ceil(Fraction(x*y, quote_after_buy))
    quantity_oracle = x-base_after_buy
    quote_left_after_reversal = math.ceil(Fraction(base_after_buy*quote_after_buy, x))
    gross_oracle = quote_after_buy-quote_left_after_reversal
    fee_out_oracle = math.ceil(Fraction(gross_oracle*rate, denominator))
    output_oracle = gross_oracle-fee_out_oracle
    assert quantity_oracle == quantity == int(projection['buy_output_atomic'])
    assert fee_in == int(projection['buy_curve_fee_lamports'])
    assert gross_oracle == int(projection['sell_gross_output_lamports'])
    assert fee_out_oracle == int(projection['sell_curve_fee_lamports'])
    assert output_oracle == int(projection['sell_output_lamports']) == 975156249
    rows.append({'mint':e['mint'], 'snapshot_observation_id':snapshot['id'],
        'period':sp['period'], 'slot':snapshot['source_slot'],
        'observed_net_curve_base_sold_atomic':str(pool['real_a']),
        'observed_real_quote_lamports':str(pool['real_b']),
        'observed_quote_vault_lamports':str(vault),
        'observed_accrued_fees_lamports':str(pool['protocol_fee_accrued']+pool['platform_fee_accrued']),
        'observed_spendable_quote_lamports':str(vault-pool['protocol_fee_accrued']-pool['platform_fee_accrued']),
        'buy_quote_observation_id':buy['id'], 'token_quantity_estimated_not_acquired':str(quantity),
        'quantity_known_before_snapshot':buy['received_at_ms'] <= snapshot['received_at_ms'],
        'observed_state_sell_check':actual,
        'counterfactual_after_own_buy_no_intervening_activity':{
            'buy_budget_lamports':str(budget), 'buy_curve_fee_lamports':str(fee_in),
            'buy_effective_input_lamports':str(effective), 'buy_output_atomic':str(quantity_oracle),
            'sell_gross_output_lamports':str(gross_oracle),
            'sell_curve_fee_lamports':str(fee_out_oracle),
            'sell_output_before_extra_costs_lamports':str(output_oracle),
            'cash_shortfall_before_extra_costs_lamports':str(budget-output_oracle),
            'arithmetic_oracle':'exact_rational_invariant_residuals_with_ceiling',
            'oracle_matches_retained_projection':True,
            'same_buy_output_as_provider':True,
            'extra_execution_costs_known':False,
            'observed_future_exit':False, 'position_acquired':False, 'execution_verified':False},
        'blocking_reasons':a['blocking_reasons']})
assert len(rows) == 4
report = {'schema':'p3-retention-independent-exit-analysis-v1',
    'evidence_bundle':'retention_003', 'tail_hash':anchor,
    'source_revision':bundle['source_revision'],
    'historical_evidence_modified':False, 'new_network_requests':0,
    'provider_quotes':provider, 'snapshot_checks':rows,
    'economic_verdict':'INSUFFICIENT DATA',
    'interpretation':'Provider rejects current-state sales with INSUFFICIENT_LIQUIDITY; observed banks have zero net sold base and only 0 or 1 spendable quote lamport. No hypothetical buy was executed. The post-buy reversal is a distinct conditional model, not a future provider quote or realized performance.',
    'remaining_blockers':['original platform administrator seed unknown',
        'provider quote source timestamp and slot unknown', 'additional execution costs unknown',
        'no acquired inventory or observed future sale', 'independent universe reference missing',
        'two candidates do not establish economic expectancy'],
    'next_informative_bounded_experiment':{
        'scope':'instrumental current-state sell compatibility; not strategy validation',
        'pre_register':'fixed native-SOL identity-qualified pool with positive net sold base and spendable quote; amount=min(reference buy output, floor(observed real_a/100)); only quote if amount>0; fixed number of later same-bank observations; preserve every refusal and state change',
        'constraints':'separate preregistration, explicit free access, max20 attempts/max60s, no transaction, no wallet, no adaptive retries',
        'limitation':'A provider sale quote in the observed bank still does not certify a later exit after our unexecuted hypothetical purchase.'}}
print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
