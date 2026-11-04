"""Moteur PAPER unifié pour les signaux comportementaux et marché.

Ce module ne signe ni n'envoie de transaction. Il transforme uniquement les
informations observables avant une entrée en décision PAPER explicable. Les
seuils de ce fichier sont une politique diagnostique pré-enregistrée : ils
doivent encore être évalués hors échantillon avant toute utilisation réelle.
"""

from dataclasses import asdict, dataclass
import math

from bot.analyser.behavior_pipeline import (
    classify_creator_behavior,
    wallet_graph_snapshot,
)


@dataclass(frozen=True)
class SignalFeatures:
    mint: str
    creator: str
    signal_time: int
    observed_at: int
    prior_launches: int
    behavior_known: bool
    relevant_transactions: int
    dev_sales: int
    relay_transfers: int
    bundle_transactions: int
    bundle_wallets: int
    liquidity_usd: float
    price_usd: float
    quote_count: int
    momentum_60s: float | None
    momentum_300s: float | None
    volume_5m_usd: float | None = None
    volume_24h_usd: float | None = None
    price_change_5m_pct: float | None = None
    price_change_1h_pct: float | None = None
    tx_buys_5m: int | None = None
    tx_sells_5m: int | None = None
    market_cap_usd: float | None = None
    fdv_usd: float | None = None
    fee_bps: float | None = None
    depth_usd: float | None = None
    slippage_bps_est: float | None = None
    market_data_quality: str = 'legacy'
    holder_count: int = 0
    top_holder_share: float | None = None
    holder_data_known: bool = False
    linked_wallets: int = 0
    wallet_link_count: int = 0
    same_slot_wallets: int = 0
    wallet_graph_transactions: int = 0
    quote_source: str = 'dex_market'
    funding_usd: float | None = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Decision:
    enter: bool
    score: float
    reasons: tuple[str, ...]
    risk_flags: tuple[str, ...]
    # ``tp_pct`` and ``sl_pct`` are percentage points, matching the
    # paper_trader contract: 12.0 means +12%, not 0.12%.
    tp_pct: float
    sl_pct: float
    hold_seconds: int
    trailing_stop_pct: float | None = None
    cost_bps: int = 200

    def to_paper_model(self):
        """Adapt this diagnostic decision to the existing PAPER ledger."""
        return {
            # This approval is issued by the final decision engine only;
            # the PAPER ledger must never substitute a legacy baseline score.
            'decision_approved': bool(self.enter),
            'decision_score': float(self.score),
            'creator_scores': {},
            'fallback_score': max(0.001, self.score / 100.0),
            'tp_pct': self.tp_pct,
            'sl_pct': self.sl_pct,
            'hold_seconds': self.hold_seconds,
            'trailing_stop_pct': self.trailing_stop_pct,
            'cost_bps': self.cost_bps,
        }


def _keys(tx):
    raw = ((tx.get('transaction') or {}).get('message') or {}).get(
        'accountKeys', []
    ) or []
    result = []
    for item in raw:
        if isinstance(item, dict):
            value = item.get('pubkey')
        else:
            value = item
        if value:
            result.append(value)
    return result


def _wallet(tx):
    keys = _keys(tx)
    return keys[0] if keys else None


def _contains_mint(tx, mint):
    # The cache contains parsed transactions; this cheap guard avoids parsing
    # unrelated creator history in the hot loop.
    return mint in str(tx)


def _reference_price(series, target, max_gap=120):
    valid = [item for item in series
             if item[0] <= target and target - item[0] <= max_gap
             and item[1] > 0 and math.isfinite(item[1])]
    return max(valid, key=lambda item: item[0]) if valid else None


def _bundle_shape(cached, mint, signal_time, observed_at):
    """Estimate same-slot coordination without claiming bundle certainty."""
    launch_rows = [
        (timestamp, tx) for timestamp, _signature, tx in cached
        if timestamp == signal_time and _contains_mint(tx, mint)
    ]
    launch_slot = None
    if launch_rows:
        launch_slot = launch_rows[0][1].get('slot')

    if launch_slot is not None:
        rows = [tx for timestamp, _signature, tx in cached
                if timestamp <= observed_at and tx.get('slot') == launch_slot
                and _contains_mint(tx, mint)]
    else:
        rows = [tx for timestamp, _signature, tx in cached
                if signal_time <= timestamp <= observed_at
                and _contains_mint(tx, mint)]
    wallets = {_wallet(tx) for tx in rows if _wallet(tx)}
    return len(rows), len(wallets)


def build_features(cached, mint, creator, signal_time, observed_at,
                   price_series, current_quote, prior_launches=0, *,
                   excluded_holder_owners=()):
    """Build features using only cache/quotes at or before ``observed_at``.

    ``excluded_holder_owners`` is passed to :func:`wallet_graph_snapshot`;
    the default keeps every observed owner in the holder statistics.
    """
    relevant = []
    for timestamp, signature, tx in cached:
        if timestamp <= signal_time or timestamp > observed_at:
            continue
        if not _contains_mint(tx, mint):
            continue
        relevant.append((timestamp, classify_creator_behavior(tx, mint, creator)))

    liquidity, price, _pair = current_quote
    market_fields = {
        name: getattr(current_quote, name, None)
        for name in (
            'volume_5m_usd', 'volume_24h_usd', 'price_change_5m_pct',
            'price_change_1h_pct', 'tx_buys_5m', 'tx_sells_5m',
            'market_cap_usd', 'fdv_usd', 'fee_bps', 'depth_usd',
            'slippage_bps_est',
        )
    }
    known_market_fields = sum(value is not None for value in market_fields.values())
    market_quality = (
        'complete' if known_market_fields == len(market_fields)
        else 'partial' if known_market_fields else 'legacy'
    )
    series = [
        (int(row[0]), float(row[1]), float(row[2] or 0))
        for row in price_series
        if len(row) >= 3 and int(row[0]) <= int(observed_at)
        and float(row[1]) > 0 and math.isfinite(float(row[1]))
    ]
    series.append((int(observed_at), float(price), float(liquidity)))
    series.sort(key=lambda item: item[0])
    compact = [(timestamp, value) for timestamp, value, _ in series]
    reference_60 = _reference_price(compact, observed_at - 60)
    reference_300 = _reference_price(compact, observed_at - 300)

    momentum_60 = (
        price / reference_60[1] - 1.0 if reference_60 else None
    )
    momentum_300 = (
        price / reference_300[1] - 1.0 if reference_300 else None
    )
    bundle_transactions, bundle_wallets = _bundle_shape(
        cached, mint, signal_time, observed_at,
    )
    wallet_graph = wallet_graph_snapshot(
        cached, mint, signal_time, observed_at,
        excluded_owners=excluded_holder_owners,
    )
    return SignalFeatures(
        mint=mint,
        creator=creator,
        signal_time=int(signal_time),
        observed_at=int(observed_at),
        prior_launches=max(0, int(prior_launches)),
        behavior_known=bool(relevant),
        relevant_transactions=len(relevant),
        dev_sales=sum(int(item['sale']) for _time, item in relevant),
        relay_transfers=sum(int(item['relay']) for _time, item in relevant),
        bundle_transactions=bundle_transactions,
        bundle_wallets=bundle_wallets,
        liquidity_usd=max(0.0, float(liquidity)),
        price_usd=max(0.0, float(price)),
        quote_count=len(series),
        momentum_60s=momentum_60,
        momentum_300s=momentum_300,
        **market_fields,
        market_data_quality=market_quality,
        holder_count=wallet_graph['holder_count'],
        top_holder_share=wallet_graph['top_holder_share'],
        holder_data_known=wallet_graph['holder_data_known'],
        linked_wallets=wallet_graph['linked_wallets'],
        wallet_link_count=wallet_graph['wallet_link_count'],
        same_slot_wallets=wallet_graph['same_slot_wallets'],
        wallet_graph_transactions=wallet_graph['source_transactions'],
        quote_source=getattr(current_quote, 'quote_source', 'dex_market'),
        funding_usd=getattr(current_quote, 'funding_usd', None),
    )


def decide(features, min_score=45.0, min_liquidity=1000.0):
    """Exploratory PAPER calibration v2; never sends or signs transactions."""
    score = 50.0; reasons = []; risks = []
    if features.prior_launches >= 5: score += 10; reasons.append('creator_historique_etabli')
    elif features.prior_launches >= 2: score += 7; reasons.append('creator_recurrent')
    elif features.prior_launches == 1: score += 3; reasons.append('creator_deja_observe')
    else: score -= 3; risks.append('creator_nouveau')

    if features.quote_source == 'launchlab_curve':
        # A LaunchLab bonding curve has no DEX LP liquidity. ``liquidity_usd``
        # carries observed curve funding for backward compatibility; applying
        # the DEX $1k LP threshold here caused systematic false rejections.
        funding = features.funding_usd if features.funding_usd is not None else features.liquidity_usd
        if funding <= 0:
            score -= 45; risks.append('funding_launchlab_absent')
        elif funding < 5:
            score -= 8; risks.append('funding_launchlab_tres_faible')
        elif funding < 25:
            score -= 3; risks.append('funding_launchlab_faible')
        elif funding >= 250:
            score += 8; reasons.append('funding_launchlab_fort')
        else:
            score += 4; reasons.append('funding_launchlab_observe')
    elif features.liquidity_usd < min_liquidity: score -= 45; risks.append('liquidite_insuffisante')
    elif features.liquidity_usd < 3000: score -= 8; risks.append('liquidite_faible')
    elif features.liquidity_usd >= 25000: score += 12; reasons.append('liquidite_forte')
    elif features.liquidity_usd >= 10000: score += 10; reasons.append('liquidite_solide')
    else: score += 5; reasons.append('liquidite_observee')

    if features.behavior_known: score += 3; reasons.append('comportement_observe')
    else: score -= 2; risks.append('comportement_inconnu')
    if features.dev_sales: score -= 70; risks.append('vente_developpeur')
    if features.relay_transfers: score -= 50; risks.append('transfert_relais')

    if features.bundle_transactions >= 2: score -= 4; risks.append('activite_meme_slot')
    if features.bundle_transactions >= 3 and features.bundle_wallets >= 2: score -= 6; risks.append('coordination_wallets_possible')
    if features.same_slot_wallets >= 3: score -= 4; risks.append('multi_wallet_meme_slot')
    if features.wallet_link_count >= 2: score -= min(8, features.wallet_link_count); risks.append('liens_wallets_observes')

    m60, m300 = features.momentum_60s, features.momentum_300s
    if m60 is not None:
        if m60 <= -0.20: score -= 30; risks.append('momentum_effondrement')
        elif m60 <= -0.10: score -= 18; risks.append('momentum_tres_negatif')
        elif m60 < -0.04: score -= 10; risks.append('momentum_negatif')
        elif m60 > 0.50: score -= 18; risks.append('fomo_extreme')
        elif m60 > 0.30: score -= 7; risks.append('fomo_excessif')
        elif 0.0 <= m60 <= 0.25: score += 6; reasons.append('momentum_constructif')
        else: score += 2; reasons.append('momentum_stable')
    if m300 is not None:
        if m300 <= -0.35: score -= 18; risks.append('tendance_5m_effondrement')
        elif m300 <= -0.20: score -= 10; risks.append('tendance_5m_negative')
        elif 0.0 <= m300 <= 0.35: score += 4; reasons.append('tendance_5m_saine')

    if features.quote_count < 2: score -= 4; risks.append('serie_prix_courte')
    elif features.quote_count >= 5: score += 3; reasons.append('serie_prix_etablie')
    if features.market_data_quality == 'legacy': score -= 1; risks.append('metriques_marche_inconnues')
    elif features.market_data_quality == 'complete': score += 2; reasons.append('metriques_marche_completes')

    if features.volume_5m_usd is not None:
        if features.volume_5m_usd <= 0: score -= 5; risks.append('volume_recent_nul')
        elif features.volume_5m_usd >= max(5000.0, features.liquidity_usd * 0.25): score += 5; reasons.append('volume_recent_actif')
    if features.tx_buys_5m is not None and features.tx_sells_5m is not None:
        buys, sells = max(0, int(features.tx_buys_5m)), max(0, int(features.tx_sells_5m))
        if buys + sells >= 6:
            if sells >= max(5, buys * 2): score -= 10; risks.append('pression_vente_recent')
            elif buys >= max(5, sells * 1.5): score += 5; reasons.append('pression_achat_observee')

    if features.holder_data_known and features.top_holder_share is not None:
        if features.top_holder_share >= 0.90: score -= 40; risks.append('concentration_extreme')
        elif features.top_holder_share >= 0.50: score -= 5; risks.append('concentration_elevee')
        elif features.top_holder_share <= 0.25: score += 4; reasons.append('concentration_moderee')
    if features.slippage_bps_est is not None:
        if features.slippage_bps_est >= 1000: score -= 25; risks.append('slippage_estime_extreme')
        elif features.slippage_bps_est >= 500: score -= 12; risks.append('slippage_estime_eleve')
        elif features.slippage_bps_est <= 150: score += 3; reasons.append('slippage_estime_faible')

    score = max(0.0, min(100.0, score))
    critical = {'vente_developpeur','transfert_relais','liquidite_insuffisante','funding_launchlab_absent','concentration_extreme','momentum_effondrement','tendance_5m_effondrement','fomo_extreme','slippage_estime_extreme'}
    enter = score >= float(min_score) and not critical.intersection(risks)

    tp, sl, hold, trailing, cost = 10.0, 8.0, 1800, 5.0, 200
    if features.liquidity_usd < 3000: tp, sl, hold, trailing, cost = 7.0, 6.0, 900, 3.5, 300
    elif features.liquidity_usd >= 25000: tp, sl, hold, trailing, cost = 14.0, 8.0, 2700, 6.0, 150
    elif m60 is not None and 0.0 <= m60 <= 0.25: tp, sl, hold, trailing = 12.0, 7.0, 1800, 5.0
    if 'activite_meme_slot' in risks or 'liens_wallets_observes' in risks: tp, sl, hold, trailing = 7.0, 5.0, 900, 3.0
    if features.slippage_bps_est is not None: cost = max(cost, min(1000, int(round(features.slippage_bps_est * 2))))
    return Decision(enter=enter, score=score, reasons=tuple(reasons), risk_flags=tuple(risks), tp_pct=tp, sl_pct=sl, hold_seconds=hold, trailing_stop_pct=trailing, cost_bps=cost)
