"""The only "node" the harness talks to: canned answers, no socket.

``simulate_transaction`` executes nothing. Its success is a fixture and says
nothing about what a mainnet node would answer for the same bytes.
"""


class FixtureRpc:
    def __init__(self, *, genesis_hash, endpoint_sha256, block_height, units_consumed=150_000):
        self.endpoint_sha256 = endpoint_sha256
        self._genesis_hash = genesis_hash
        self.block_height = block_height
        self.units_consumed = units_consumed
        self.simulated = []  # exact unsigned wires that reached the fixture

    async def genesis_hash(self):
        return self._genesis_hash

    async def get_block_height(self):
        return self.block_height

    async def simulate_transaction(self, raw, *, sig_verify, min_context_slot=None):
        # One signature slot, all zero: anything else is not an unsigned order.
        if sig_verify is not False or type(raw) is not bytes or raw[:65] != b'\x01' + bytes(64):
            raise ValueError('dry_run_accepts_only_unsigned_wire')
        self.simulated.append(raw)
        return dict(context_slot=min_context_slot, err=None, unitsConsumed=self.units_consumed,
                    logs=['dry-run fixture response: nothing was simulated by a node'])

    async def send_transaction(self, *args, **kwargs):
        raise RuntimeError('dry_run_never_sends')
