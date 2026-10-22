import hashlib
import json
import unittest
from pathlib import Path
from bot.scanner.transaction_parser import find_raydium_launch, RAYDIUM_LAUNCHPAD_PROGRAM_ID
from bot.scanner.launch_detector import parse_launch_candidate
from datetime import datetime, timezone

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
def b58(data):
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + out

class LaunchLabParserTests(unittest.TestCase):
    def test_swap_not_a_launch(self):
        tx = json.loads((Path(__file__).parent / 'sample_sell_transaction.json').read_text(encoding='utf-8'))
        self.assertIsNone(find_raydium_launch(tx))
        self.assertEqual(parse_launch_candidate(tx, datetime.now(timezone.utc))['mints'], [])

    def test_initialize_v2_inner_instruction(self):
        accounts = [f"account{i}" for i in range(18)]
        data = b58(hashlib.sha256(b'global:initialize_v2').digest()[:8] + b'payload')
        ix = {'programId': RAYDIUM_LAUNCHPAD_PROGRAM_ID, 'accounts': accounts, 'data': data}
        tx = {'transaction': {'message': {'instructions': []}}, 'meta': {'err': None, 'innerInstructions': [{'index': 0, 'instructions': [ix]}]}}
        result = find_raydium_launch(tx)
        self.assertEqual(result['mint'], 'account6')
        self.assertEqual(result['creator'], 'account1')
        self.assertEqual(parse_launch_candidate(tx, datetime.now(timezone.utc))['mints'], ['account6'])

    def test_swap_discriminator_never_creates(self):
        ix = {'programId': RAYDIUM_LAUNCHPAD_PROGRAM_ID, 'accounts': [f'account{i}' for i in range(18)], 'data': b58(hashlib.sha256(b'global:sell_exact_in').digest()[:8])}
        tx = {'transaction': {'message': {'instructions': [ix]}}, 'meta': {'err': None}}
        self.assertIsNone(find_raydium_launch(tx))

    def test_failed_tx_never_creates(self):
        ix = {'programId': RAYDIUM_LAUNCHPAD_PROGRAM_ID, 'accounts': [f'account{i}' for i in range(18)], 'data': b58(hashlib.sha256(b'global:initialize_v2').digest()[:8])}
        tx = {'transaction': {'message': {'instructions': [ix]}}, 'meta': {'err': {'InstructionError': [0, 'Custom']}}}
        self.assertIsNone(find_raydium_launch(tx))

if __name__ == '__main__':
    unittest.main()
