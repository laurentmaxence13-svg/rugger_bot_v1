import asyncio
import unittest
from types import SimpleNamespace

from bot.analyser.multi_creator_research_engine import (
    AdaptiveRPCGate, retry_after_seconds, rpc_json, signatures,
)


class Response:
    def __init__(self, status, data, headers=None):
        self.status, self.data, self.headers = status, data, headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self, **kwargs):
        return self.data


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def post(self, *args, **kwargs):
        self.calls += 1
        return next(self.responses)


class FastGate(AdaptiveRPCGate):
    async def wait_turn(self):
        self.calls += 1


class ResearchRPCTests(unittest.IsolatedAsyncioTestCase):
    async def test_429_retries_and_sets_shared_cooldown(self):
        session = Session([Response(429, {}, {'Retry-After': '3'}), Response(200, {'result': [1]})])
        gate = FastGate()
        result = await rpc_json(SimpleNamespace(session=session), 'https://unused', gate, 'method', [])
        self.assertEqual(result, [1])
        self.assertEqual(session.calls, 2)
        self.assertEqual(gate.rate_limits, 1)
        self.assertGreater(gate.cooldown_until, 0)
        self.assertGreaterEqual(gate.interval, 1.98)

    async def test_exhaustion_does_not_look_like_empty_history(self):
        session = Session([Response(429, {}) for _ in range(8)])
        with self.assertRaisesRegex(RuntimeError, 'échec après 8 tentatives'):
            await signatures(SimpleNamespace(session=session), 'https://unused', FastGate(), 'address', 1)

    async def test_non_retryable_error_fails_fast(self):
        session = Session([Response(401, {})])
        with self.assertRaisesRegex(RuntimeError, 'HTTP 401'):
            await rpc_json(SimpleNamespace(session=session), 'https://unused', FastGate(), 'method', [])
        self.assertEqual(session.calls, 1)

    def test_retry_after(self):
        self.assertEqual(retry_after_seconds('3'), 3)
        self.assertIsNone(retry_after_seconds('invalid'))


if __name__ == '__main__':
    unittest.main()
