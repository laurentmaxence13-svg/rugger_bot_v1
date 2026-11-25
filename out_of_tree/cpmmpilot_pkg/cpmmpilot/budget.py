"""Credit budget of the pilot: same discipline as bot.market.backfill.CreditBudget (charge BEFORE the send, ledger written
atomically on disk before the request leaves, cost table pinned in the ledger, a resume never restarts from a lower
counter), extended to the methods of the pilot. CreditBudget itself is not reused because its constructor accepts only
the three read methods of the W1 backfill (READ_METHODS); the shared methods carry the same costs (test).

Costs = Helius grid archived 08/11 (pricing b6794b16, credits fa152d54): standard RPC 1 credit; getProgramAccounts 10;
getTransactionsForAddress 10 per 100 full transactions returned, minimum 10 -> 10 charged BEFORE each call, whose
limit is capped at 100 (the documented maximum of one call).
"""
import json
import os
from pathlib import Path

SCHEMA = 'cpmmpilot-spend-v1'
COSTS = {'getSlot': 1, 'getProgramAccounts': 10, 'getMultipleAccounts': 1, 'getSignaturesForAddress': 1,
         'getTransaction': 1, 'getTransactionsForAddress': 10}
GTFA_MAX_LIMIT = 100

# caps of the owner texts (R02 v1.2)
STEP0_CAP = 100
U2_CAP = 5_000
T2_CAP = 1_470                     # 0.2.6: owner T2 (1 500) at 98 % (R02 18:01Z)
STAGES = ('step0', 'u2', 'step1', 't2', 'g23', 'livesim')    # 0.2.9: 'livesim' (R04-10), its cap is the owner's P
G23_CAP = 32_340                   # 0.2.8: G2-3 window collection (33 000) at 98 % (R02 20:42Z), own stage and ledger
STEP1_CAP = 50_000
STEP1_HARD_STOP = 49_000            # 98 % of 50 000
POINT2_LIMIT = 32_900               # text C (ii): 24 x R x 8 x c_tx + 400 > 32 900 -> STOP before the count
C_TX_GTFA = 0.10                    # credits per full transaction with GTFA (10 per 100)
STEP1_OVERHEAD = 400


class BudgetExhausted(RuntimeError):
    pass


class BudgetError(ValueError):
    pass


def _write_atomic(path, data):
    tmp = Path(str(path) + '.tmp')
    with open(tmp, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class PilotBudget:
    def __init__(self, ledger, *, stage, max_credits):
        if stage not in STAGES:
            raise BudgetError('unknown_stage')
        if type(max_credits) is not int or max_credits <= 0:
            raise BudgetError('cap_must_be_a_positive_integer')
        self.ledger, self.stage, self.max_credits = Path(ledger), stage, max_credits
        self.requests = self.credits = 0
        self.by_method = {}
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        if self.ledger.exists():
            data = json.loads(self.ledger.read_text())
            if data.get('schema') != SCHEMA or data.get('stage') != stage:
                raise BudgetError('ledger_of_another_stage_or_schema')
            if data['costs'] != dict(sorted(COSTS.items())):
                raise BudgetError('cost_table_differs_from_ledger')
            if data['max_credits'] != max_credits:
                raise BudgetError('cap_differs_from_ledger')
            self.requests, self.credits = data['requests'], data['credits']
            self.by_method = data['by_method']
        self._write()

    def _write(self):
        _write_atomic(self.ledger, json.dumps(dict(
            schema=SCHEMA, stage=self.stage, max_credits=self.max_credits, requests=self.requests,
            credits=self.credits, by_method=dict(sorted(self.by_method.items())),
            costs=dict(sorted(COSTS.items()))), indent=1, sort_keys=True).encode())

    def charge(self, method, params=None):
        if method not in COSTS:
            raise BudgetError('method_not_priced:%s' % method)
        if method == 'getTransactionsForAddress':
            limit = (params or [None, {}])[1].get('limit')
            if type(limit) is not int or not 1 <= limit <= GTFA_MAX_LIMIT:
                raise BudgetError('gtfa_limit_must_be_1_to_100')
        cost = COSTS[method]
        if self.credits + cost > self.max_credits:
            raise BudgetExhausted('credit_cap_reached:%d' % self.max_credits)
        self.requests += 1
        self.credits += cost
        self.by_method[method] = self.by_method.get(method, 0) + cost
        self._write()                       # on disk BEFORE the request leaves

    def snapshot(self):
        return dict(stage=self.stage, requests=self.requests, credits=self.credits, max_credits=self.max_credits,
                    by_method=dict(sorted(self.by_method.items())))


def point2_stop(r_hat):
    """Text C (ii) of R02 v1.2: STOP before the trigger count if 24 x R^ x 8 x c_tx + 400 > 32 900."""
    if not isinstance(r_hat, (int, float)) or r_hat < 0:
        raise BudgetError('r_hat_must_be_non_negative')
    need = 24 * r_hat * 8 * C_TX_GTFA + STEP1_OVERHEAD
    return dict(r_hat=r_hat, need=need, limit=POINT2_LIMIT, stop=need > POINT2_LIMIT)


def d_max_days(r_hat):
    """D_max = (32 900 - 400) / (24 x R^ x c_tx) - 7 (method U-2 v0.2 D-e); None when R^ = 0."""
    if r_hat <= 0:
        return None
    return (POINT2_LIMIT - STEP1_OVERHEAD) / (24 * r_hat * C_TX_GTFA) - 7
