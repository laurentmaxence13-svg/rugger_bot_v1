"""Step 0 (owner text A): read the public vectors V-1' (50 to 100 CPMM transactions, list fixed by the protocol and
pinned by its sha) with getTransaction, at most 100 credits; raw results written gz; then R02 audits the decoder."""
from pathlib import Path

from .rpc import sha
from .store import file_sha, write_gz_page, write_json


class Step0Stop(RuntimeError):
    pass


def run(client, out, vectors_file, vectors_sha256):
    path = Path(vectors_file)
    if file_sha(path) != vectors_sha256:
        raise Step0Stop('vector_list_is_not_the_anchored_one')
    signatures = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if not 50 <= len(signatures) <= 100 or len(set(signatures)) != len(signatures):
        raise Step0Stop('vector_list_must_hold_50_to_100_distinct_signatures')
    missing = 0
    for k, signature in enumerate(signatures):
        tx = client.call('getTransaction', [signature, dict(encoding='json', maxSupportedTransactionVersion=0)])
        missing += tx is None
        write_gz_page(Path(out) / 'vectors' / ('%03d.json.gz' % k), dict(signature=signature, result=tx))
    doc = dict(schema='cpmmpilot-step0-v0.1', vectors=len(signatures), missing=missing,
               vectors_sha256=vectors_sha256, budget=client.budget.snapshot())
    write_json(Path(out) / 'STEP0.json', doc)
    return doc
