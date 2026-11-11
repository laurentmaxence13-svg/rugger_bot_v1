"""t22pol: the policy table agrees with the frozen reader on every extension type (synthetic mints)."""
import base64
import json
import struct

import pytest

from bot.p3.token2022 import TokenEvidenceError, decode_mint
from t22pol import census, policy

MINT = '11111111111111111111111111111112'          # any valid 32-byte address
MINT_RAW = bytes(31) + b'\x01'


def base(mint_authority=False, freeze_authority=False):
    raw = bytearray(82)
    struct.pack_into('<I', raw, 0, int(mint_authority))
    struct.pack_into('<Q', raw, 36, 10**15)
    raw[44], raw[45] = 6, 1
    struct.pack_into('<I', raw, 46, int(freeze_authority))
    return bytes(raw)


def metadata_value():
    def text(s):
        return struct.pack('<I', len(s)) + s
    return bytes(32) + MINT_RAW + text(b'Name') + text(b'SYM') + text(b'https://x') + struct.pack('<I', 0)


def tlv(kind, value):
    return struct.pack('<HH', kind, len(value)) + value


def t22_mint(extensions, **authorities):
    raw = base(**authorities) + bytes(165 - 82) + b'\x01' + b''.join(tlv(k, v) for k, v in extensions)
    return dict(owner=policy.TOKEN_2022_PROGRAM, executable=False, lamports=10**7,
                data=[base64.b64encode(raw).decode(), 'base64'])


ALLOWED = [(18, bytes(32) + MINT_RAW), (19, metadata_value())]


def test_rent_matches_the_runtime_formula():
    assert policy.rent_exempt_lamports(165) == 2_039_280
    assert policy.rent_exempt_lamports(170) == 2_074_080


def test_table_covers_every_official_value_once():
    values = [row[0] for row in policy.EXTENSIONS]
    assert values == list(range(29))
    assert policy.MINT_ALLOW == {18, 19} and policy.OUR_ACCOUNT_ALLOW == {7}


def test_spl_mint_is_executable_now_and_authorities_refuse():
    spl = dict(owner=policy.TOKEN_PROGRAM, executable=False, lamports=1,
               data=[base64.b64encode(base()).decode(), 'base64'])
    assert policy.classify(spl, MINT)['class_'] == 'executable_now'
    frozen = dict(spl, data=[base64.b64encode(base(freeze_authority=True)).decode(), 'base64'])
    assert policy.classify(frozen, MINT)['reasons'] == ['freeze_authority_present']


def test_metadata_only_token2022_is_allowlisted_and_the_frozen_reader_agrees():
    account = t22_mint(ALLOWED)
    row = policy.classify(account, MINT)
    assert row['class_'] == 'token2022_allowlisted' and row['extensions'] == ['MetadataPointer', 'TokenMetadata']
    assert row['our_account_rent_lamports'] == 2_074_080
    facts, _raw = decode_mint(account, MINT)
    assert facts['extension_types'] == [18, 19]


@pytest.mark.parametrize('kind', [k for k in range(1, 29) if k not in (18, 19)])
def test_every_other_extension_is_refused_by_the_table_and_by_the_frozen_reader(kind):
    account = t22_mint(ALLOWED + [(kind, bytes(8))])
    row = policy.classify(account, MINT)
    assert row['class_'] == 'refused' and row['reasons'] == [f'extension_refused:{policy.name(kind)}']
    with pytest.raises(TokenEvidenceError):
        decode_mint(account, MINT)


def test_unknown_future_extension_is_refused():
    row = policy.classify(t22_mint(ALLOWED + [(29, b'')]), MINT)
    assert row['reasons'] == ['extension_refused:unknown_29']


def test_authorities_refuse_even_with_allowed_extensions():
    row = policy.classify(t22_mint(ALLOWED, mint_authority=True, freeze_authority=True), MINT)
    assert row['class_'] == 'refused'
    assert row['reasons'] == ['mint_authority_present', 'freeze_authority_present']


def test_unreadable_or_foreign_mints_are_refused():
    assert policy.classify(None, MINT)['reasons'] == ['mint_account_missing_or_invalid']
    foreign = dict(owner='11111111111111111111111111111111', executable=False, data=['', 'base64'])
    assert policy.classify(foreign, MINT)['class_'] == 'refused'


def test_census_counts_and_checks_the_frozen_reader(tmp_path, capsys):
    pools = [dict(pool='p1', mint=MINT, mint_account=t22_mint(ALLOWED)),
             dict(pool='p2', mint=MINT, mint_account=t22_mint(ALLOWED + [(1, bytes(108))])),
             dict(pool='p3', mint=MINT, mint_account=dict(owner=policy.TOKEN_PROGRAM, executable=False,
                                                          data=[base64.b64encode(base()).decode(), 'base64']))]
    out = census.census(dict(pools=pools), frozen_check=True)
    assert out['classes'] == {'executable_now': 1, 'refused': 1, 'token2022_allowlisted': 1}
    assert out['refusal_reasons'] == {'extension_refused:TransferFeeConfig': 1}
    assert out['disagreements_with_frozen_reader'] == []
    path = tmp_path / 'pools.json'
    path.write_text(json.dumps(dict(pools=pools)))
    assert census.main([str(path), '--frozen-check']) == 0
    assert json.loads(capsys.readouterr().out)['pools'] == 3
