"""P3 du pré-mortem (R01, déclaré à R02 avant lecture) : coûts modélisés contre swaps réels, pages PRÉ-T0 des 4 pools
nommés (dossier fictif R03 6e27bf5), calcul direct par les fonctions gelées. Aucun rendement.
python -B -I p3_check.py U2.json ROOT OUT_JSON"""
import hashlib
import json
import sys
from pathlib import Path

from cpmmcost import model as CC
from cpmmpilot import step1 as PILOT
from cpmmx import curve, timeline as TL
from g23run import run as G

LOW, HIGH = 50_000_000, 200_000_000
STAKE = CC.STAKE_LAMPORTS
START, END = 1794910886, 1795515686


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else None


def summ(xs):
    return dict(n=len(xs), p10=pct(xs, 0.1), p50=pct(xs, 0.5), p90=pct(xs, 0.9), max=max(xs) if xs else None)


def quote_side(s):
    """(WSOL amount, quote reserve before, base reserve before) of a logged swap; buys put WSOL in."""
    e = s.event
    if s.side == 'buy':
        return e.input_amount, e.input_vault_before, e.output_vault_before
    return e.output_amount, e.output_vault_before, e.input_vault_before


def impact_of_buy(amount, q, b, fees, on_input):
    """Price impact share of a WSOL buy of `amount` on (b, q): 1 - output / (amount net of fee x spot)."""
    got = curve.swap_base_input(amount, q, b, fees, on_input)
    net_in = amount - got.trade_fee - (got.creator_fee if on_input else 0)
    ideal = net_in * b / q
    return 1 - got.output_amount / ideal


def main(u2_path, root, out):
    u2 = json.loads(Path(u2_path).read_text())
    selected = [r for r in u2['selected'] if r['pool'] in G.POOLS]
    config = PILOT.amm_config_for_rules(selected, u2['t0_slot'])
    fees = CC.fees_from_amm_config(config)
    by_pool = {r['pool']: r for r in selected}
    res = dict(config=dict(trade_fee_rate=fees.trade_fee_rate, creator_fee_rate_charged=fees.creator_fee_rate,
                           creator_fee_rate_declared=config.get('creator_fee_rate'),
                           protocol_fee_rate=fees.protocol_fee_rate, fund_fee_rate=fees.fund_fee_rate),
               window=[START, END], band_lamports=[LOW, HIGH], pools={})
    for pool in G.POOLS:
        line, _txs = G.window_line(pool, by_pool[pool]['base_mint'], Path(root) / pool, start=START, end=END)
        exact, dev, fee_ok, fee_eff, creator_eff, real_imp, model_imp_same, model_imp_01 = 0, [], 0, [], [], [], [], []
        n, transfer_fee, errors = 0, 0, {}
        for s in line.swaps:
            e = s.event
            amt, q, b = quote_side(s)
            if not LOW <= amt <= HIGH:
                continue
            n += 1
            if e.input_transfer_fee or e.output_transfer_fee:
                transfer_fee += 1
            try:
                if e.base_input:
                    got = curve.swap_base_input(e.input_amount, e.input_vault_before, e.output_vault_before, fees,
                                                e.creator_fee_on_input)
                    real, model = e.output_amount, got.output_amount
                else:
                    got = curve.swap_base_output(e.output_amount, e.input_vault_before, e.output_vault_before, fees,
                                                 e.creator_fee_on_input)
                    real, model = e.input_amount, got.input_amount
            except curve.CurveError as exc:
                errors[str(exc)] = errors.get(str(exc), 0) + 1
                continue
            exact += real == model
            dev.append(abs(real - model) / model)
            if e.trade_fee is not None:
                fee_ok += e.trade_fee == got.trade_fee
                fee_in = e.input_amount
                fee_eff.append(e.trade_fee / fee_in * 1e6)
                if e.creator_fee is not None:
                    creator_eff.append(e.creator_fee / (fee_in if e.creator_fee_on_input else e.output_amount) * 1e6)
            on_input = e.creator_fee_on_input
            try:
                model_imp_01.append(impact_of_buy(STAKE, q, b, fees, on_input))
                model_imp_same.append(impact_of_buy(amt, q, b, fees, on_input))
                if s.side == 'buy' and e.base_input:
                    net_in = e.input_amount - got.trade_fee - (got.creator_fee if on_input else 0)
                    real_imp.append(1 - e.output_amount / (net_in * b / q))
            except curve.CurveError:
                pass
        res['pools'][pool] = dict(
            swaps_in_band=n, with_transfer_fee=transfer_fee, errors=errors,
            output_exact_share=exact / n if n else None, relative_deviation=summ(dev),
            trade_fee_exact_share=fee_ok / len(fee_eff) if fee_eff else None,
            effective_trade_fee_ppm=summ(fee_eff), effective_creator_fee_ppm=summ(creator_eff),
            realized_impact_share_real_buys=summ(real_imp), modeled_impact_share_same_amount=summ(model_imp_same),
            modeled_impact_share_at_0_1_SOL=summ(model_imp_01))
    text = json.dumps(res, indent=1, sort_keys=True) + '\n'
    Path(out).write_text(text)
    print(out, hashlib.sha256(text.encode()).hexdigest())


if __name__ == '__main__':
    main(*sys.argv[1:4])
