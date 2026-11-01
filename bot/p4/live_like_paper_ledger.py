"""Event-sourced, dual-arm, read-only PAPER fill ledger.

This is a replay engine, not a Solana transaction sender. Price envelopes must
reference previously observed on-chain receipts or source provider quotes;
modeled fills are explicitly optimistic/conditional, NOT executable orders.

Two arms share exactly the same as-of observations and fixed capital.
Unknown fees, censored exits, stale clocks and unverified migrations fail shut.
Never substitute a pool model's price for an independently executable quote
without retaining the MODEL_CONDITIONAL qualification.
"""
import hashlib
import json

SCHEMA="rugger-dual-arm-live-like-paper-ledger-v1"
ARMS=("master","reference")
ACTS=("ENTER","WAIT","REJECT")
VENUES=("LAUNCHLAB_CURVE","RAYDIUM_CPMM")
PROVENANCES=("OBSERVED_CHAIN_MODEL","INDEPENDENT_PROVIDER_QUOTE")
MAX_U64=2**64-1


def sha(document):
    return hashlib.sha256(json.dumps(document,sort_keys=True,separators=(",",":"),
                allow_nan=False).encode()).hexdigest()


def integer(value,name,minimum=0):
    if type(value) is not int or not minimum<=value<=MAX_U64:
        raise ValueError(name+"_invalid")
    return value


def address(value,name):
    if type(value) is not str or not value or len(value)>128:
        raise ValueError(name+"_invalid")
    return value


def source_quote(data):
    """Strict exact-lot, fully costed, independently timestamped observation."""
    if type(data) is not dict or set(data)!={
        "id","mint","pool","venue","side","input_atomic","output_atomic",
        "source_slot","available_at_ms","source_produced_at_ms",
        "source_observation_sha256",
        "provenance","network_and_priority_fee_lamports",
        "account_creation_fee_lamports","failed_attempt_fee_lamports",
        "migration_proof"}:
        raise ValueError("exact_quote_evidence_required")
    for k in ("id","mint","pool"):address(data[k],k)
    if data["venue"] not in VENUES or data["side"] not in ("BUY","SELL"):
        raise ValueError("phase_and_side_required")
    if data["provenance"] not in PROVENANCES:
        raise ValueError("exact_price_source_class_required")
    for k in ("source_slot","available_at_ms","source_produced_at_ms",
              "input_atomic","output_atomic"):
        integer(data[k],k,1)
    if data["source_produced_at_ms"]>data["available_at_ms"]:
        raise ValueError("quote_source_clock_after_availability")
    for k in ("network_and_priority_fee_lamports",
              "account_creation_fee_lamports","failed_attempt_fee_lamports"):
        integer(data[k],k)
    if (type(data["source_observation_sha256"]) is not str
            or len(data["source_observation_sha256"])!=64
            or any(c not in "0123456789abcdef" for c in
                   data["source_observation_sha256"])):
        raise ValueError("source_receipt_sha256_required")
    return data


def migration_proof(proof,*,mint,from_pool,to_pool,slot):
    if (type(proof) is not dict or set(proof)!={
        "mint","from_pool","to_pool","source_slot",
        "signed_transaction_verified","transaction_sha256"}):
        raise ValueError("exact_signed_migration_proof_required")
    if (proof["mint"]!=mint or proof["from_pool"]!=from_pool
            or proof["to_pool"]!=to_pool or
            proof["signed_transaction_verified"] is not True
            or type(proof["source_slot"]) is not int
            or not 0<proof["source_slot"]<=slot
            or type(proof["transaction_sha256"]) is not str
            or len(proof["transaction_sha256"])!=64):
        raise ValueError("unverified_or_wrong_cpmm_migration")
    return proof


def freeze_decision(case):
    """Immutable before-future-decision receipt; both arms included at once."""
    required={"id","mint","creator","pool","source_slot","available_at_ms",
              "decisions","signed_creator_verified","asof_features_verified",
              "source_quote_clock_verified","policy_sha256",
              "entry_size_lamports"}
    if type(case) is not dict or set(case)!=required:
        raise ValueError("exact_frozen_decision_case_required")
    for k in ("id","mint","creator","pool"):address(case[k],k)
    integer(case["source_slot"],"source_slot",1)
    integer(case["available_at_ms"],"decision_at_ms",1)
    integer(case["entry_size_lamports"],"entry_size_lamports",1)
    if (type(case["decisions"]) is not dict
            or set(case["decisions"])!=set(ARMS)
            or any(case["decisions"][k] not in ACTS for k in ARMS)):
        raise ValueError("both_actual_strategy_decisions_required")
    if (type(case["signed_creator_verified"]) is not bool
            or type(case["asof_features_verified"]) is not bool
            or type(case["source_quote_clock_verified"]) is not bool):
        raise ValueError("explicit_evidence_boolean_required")
    if (type(case["policy_sha256"]) is not str or len(case["policy_sha256"])!=64):
        raise ValueError("frozen_policy_hash_required")
    if (any(v=="ENTER" for v in case["decisions"].values())
            and not all(case[k] is True for k in (
                "signed_creator_verified","asof_features_verified",
                "source_quote_clock_verified"))):
        raise ValueError("unverified_entry_not_admissible")
    frozen=dict(schema=SCHEMA,case=case,phase="FROZEN_BEFORE_FILL",
        financial_order_submitted=False,actual_fill_verified=False)
    frozen["freeze_sha256"]=sha(frozen)
    return frozen


class PaperLedger:
    """Pure two-account state machine; no provider I/O and no wallets."""
    def __init__(self,*,capital_lamports=10_000_000_000,
                 minimum_delay_ms=250,max_quote_age_ms=5000,max_open=3):
        integer(capital_lamports,"capital",1)
        integer(minimum_delay_ms,"latency")
        integer(max_quote_age_ms,"max_quote_age",1)
        integer(max_open,"max_open",1)
        self.config=dict(initial_capital_lamports=capital_lamports,
                         min_delay_ms=minimum_delay_ms,
                         max_source_age_ms=max_quote_age_ms,max_open=max_open)
        self.ledger={k:dict(cash_lamports=capital_lamports,
                            positions={},closed=[],fees_paid_lamports=0)
                     for k in ARMS}
        self.cases={}
        self.used_quote_ids=set()
        self.events=[]
        self._last_time=0

    def register(self,frozen):
        if (type(frozen) is not dict
                or frozen.get("schema")!=SCHEMA
                or frozen.get("phase")!="FROZEN_BEFORE_FILL"
                or frozen.get("actual_fill_verified") is not False
                or frozen.get("financial_order_submitted") is not False):
            raise ValueError("signed_frozen_case_required")
        if sha({k:v for k,v in frozen.items() if k!="freeze_sha256"})!=frozen.get("freeze_sha256"):
            raise ValueError("freeze_was_modified_after_decision")
        case=frozen["case"]
        freeze_decision(case)
        if case["id"] in self.cases:
            raise ValueError("duplicate_decision_case")
        if case["available_at_ms"]<self._last_time:
            raise ValueError("noncausal_decision_order")
        self.cases[case["id"]]=frozen
        self._last_time=case["available_at_ms"]
        self.events.append(dict(type="PRECOMMITTED_DECISION",
            case_id=case["id"],at_ms=self._last_time,
            decisions=case["decisions"],receipt=frozen["freeze_sha256"]))

    def quote(self,case_id,arm,side,evidence):
        """Attempt PAPER order only when the quote is post-decision and full-size."""
        if case_id not in self.cases or arm not in ARMS or side not in ("BUY","SELL"):
            raise ValueError("registered_case_arm_side_required")
        q=source_quote(evidence)
        frozen=self.cases[case_id]
        case=frozen["case"]
        if (arm,q["id"]) in self.used_quote_ids:
            raise ValueError("quote_receipt_reuse_forbidden")
        if q["mint"]!=case["mint"]:
            raise ValueError("quote_mint_mismatch")
        if q["side"]!=side:
            raise ValueError("side_source_mismatch")
        if (q["source_slot"]<=case["source_slot"]
                or q["available_at_ms"]<case["available_at_ms"]+self.config["min_delay_ms"]
                or q["available_at_ms"]<self._last_time
                or q["available_at_ms"]-case["available_at_ms"]>
                   24*3600*1000
                or q["available_at_ms"]-q["source_produced_at_ms"]>
                   self.config["max_source_age_ms"]):
            raise ValueError("stale_or_noncausal_market_quote")
        state=self.ledger[arm]
        if case["decisions"][arm]!="ENTER":
            raise ValueError("policy_abstention_has_no_position")
        current=state["positions"].get(case_id)
        if side=="BUY":
            if current is not None or len(state["positions"])>=self.config["max_open"]:
                raise ValueError("duplicate_position_or_capacity_exceeded")
            if q["pool"]!=case["pool"] or q["venue"]!="LAUNCHLAB_CURVE" or q["migration_proof"] is not None:
                raise ValueError("entry_requires_original_launchlab_curve")
            spend=q["input_atomic"]
            if spend!=case["entry_size_lamports"]:
                raise ValueError("entry_size_not_equal_to_frozen_decision")
            costs=sum(q[k] for k in ("network_and_priority_fee_lamports",
                    "account_creation_fee_lamports","failed_attempt_fee_lamports"))
            if spend+costs>state["cash_lamports"]:
                raise ValueError("insufficient_paper_cash")
            state["cash_lamports"]-=spend+costs
            state["fees_paid_lamports"]+=costs
            state["positions"][case_id]=dict(
                mint=q["mint"],pool=q["pool"],venue=q["venue"],
                quantity_atomic=q["output_atomic"],entry_spend_lamports=spend,
                entry_cost_lamports=costs,
                entry_slot=q["source_slot"],entry_at_ms=q["available_at_ms"],
                entry_provenance=q["provenance"])
            effect="PAPER_BUY_MODELED_NOT_ACTUAL"
        else:
            if current is None:
                raise ValueError("sell_without_paper_inventory")
            if (q["input_atomic"]!=current["quantity_atomic"]
                    or q["source_slot"]<=current["entry_slot"]
                    or q["available_at_ms"]<=current["entry_at_ms"]):
                raise ValueError("sell_lot_not_owned_or_exit_not_later")
            if q["venue"]!=current["venue"] or q["pool"]!=current["pool"]:
                if (current["venue"]!="LAUNCHLAB_CURVE"
                        or q["venue"]!="RAYDIUM_CPMM"):
                    raise ValueError("unsupported_cross_venue_exit")
                migration_proof(q["migration_proof"],mint=q["mint"],
                    from_pool=current["pool"],to_pool=q["pool"],
                    slot=q["source_slot"])
            elif q["migration_proof"] is not None:
                raise ValueError("unnecessary_or_ambiguous_migration_proof")
            costs=sum(q[k] for k in ("network_and_priority_fee_lamports",
                    "account_creation_fee_lamports","failed_attempt_fee_lamports"))
            proceeds=q["output_atomic"]
            # Explicit costs cannot be silently deducted from a third-party quote:
            # quote output is net of venue fees but BEFORE network/ATA/failed costs.
            if proceeds<costs:
                raise ValueError("insufficient_exit_proceeds_to_pay_costs")
            state["cash_lamports"]+=proceeds-costs
            state["fees_paid_lamports"]+=costs
            pnl=proceeds-costs-current["entry_spend_lamports"]-current["entry_cost_lamports"]
            state["closed"].append(dict(case_id=case_id,mint=q["mint"],
                input_atomic=current["quantity_atomic"],gross_entry_spend_lamports=
                current["entry_spend_lamports"],net_pnl_lamports=pnl,
                entry_cost_lamports=current["entry_cost_lamports"],
                exit_cost_lamports=costs,market_exit_lamports=proceeds,
                migration_to_cpmm=current["venue"]!=q["venue"],
                paper_only=True,
                model_conditioned_price=(q["provenance"]=="OBSERVED_CHAIN_MODEL"
                    or current["entry_provenance"]=="OBSERVED_CHAIN_MODEL")))
            del state["positions"][case_id]
            effect="PAPER_SELL_MODELED_NOT_ACTUAL"
        self._last_time=q["available_at_ms"]
        self.used_quote_ids.add((arm,q["id"]))
        self.events.append(dict(type=effect,case_id=case_id,arm=arm,
            quote_id=q["id"],slot=q["source_slot"],
            at_ms=q["available_at_ms"],venue=q["venue"],
            price_provenance=q["provenance"],
            financial_order_submitted=False,
            actual_transaction_fill=False))
        return self.events[-1]

    def snapshot(self):
        accounts={}
        for arm,state in self.ledger.items():
            closed_net=sum(row["net_pnl_lamports"] for row in state["closed"])
            open_count=len(state["positions"])
            accounts[arm]=dict(cash_lamports=state["cash_lamports"],
                open_positions=open_count,
                open_inventory=list(state["positions"].values()),
                closed_paper_cycles=len(state["closed"]),
                closed_paper_net_pnl_lamports=closed_net,
                extra_network_and_account_fees_lamports=state["fees_paid_lamports"],
                capital_mark_to_market_lamports=None if open_count else state["cash_lamports"],
                complete_cycle_net_pnl_lamports=None if open_count else closed_net,
                model_only_not_actual_trading=True,
                conditional_on_observed_or_provider_quote_fills=True,
                closed_trades=list(state["closed"]))
        any_closed=any(accounts[arm]["closed_paper_cycles"]>0 for arm in ARMS)
        comparable=(any_closed and all(
            accounts[arm]["complete_cycle_net_pnl_lamports"] is not None
            for arm in ARMS))
        # Two WAIT decisions do not establish a measured zero edge: no
        # trades means no economically informative comparison.
        edge=(accounts["master"]["complete_cycle_net_pnl_lamports"]-
              accounts["reference"]["complete_cycle_net_pnl_lamports"]
              if comparable else None)
        return dict(schema=SCHEMA,accounts=accounts,
            frozen_decisions=len(self.cases),
            event_count=len(self.events),
            policy_paired_model_net_edge_lamports=edge,
            paired_net_edge_is_not_live_strategy_proof=True,
            open_inventory_present=any(accounts[k]["open_positions"] for k in ARMS),
            any_model_conditional_prices=any(e.get("price_provenance")=="OBSERVED_CHAIN_MODEL"
                for e in self.events),
            exact_live_profitability_verified=False,
            actual_financial_orders_submitted=0,
            actual_sol_spent=0,
            live_ready_to_arm=False,events=list(self.events))
