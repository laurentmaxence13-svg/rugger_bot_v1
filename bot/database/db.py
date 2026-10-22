import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Optional

SCHEMA = '''
CREATE TABLE IF NOT EXISTS launch_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol TEXT NOT NULL,
    signature TEXT NOT NULL UNIQUE,
    slot INTEGER NOT NULL,
    block_time INTEGER,
    detected_at TEXT NOT NULL,
    mint TEXT,
    deployer_candidate TEXT,
    detection_latency_ms INTEGER,
    status TEXT NOT NULL,
    pool_state TEXT
);
'''

class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(self.path, timeout=30.0, isolation_level=None)) as con:
            con.execute('PRAGMA busy_timeout=30000')
            con.executescript(SCHEMA)
            cols = {row[1] for row in con.execute("PRAGMA table_info(launch_candidates)")}
            if "pool_state" not in cols:
                con.execute("ALTER TABLE launch_candidates ADD COLUMN pool_state TEXT")

    def save_candidate(
        self,
        *,
        protocol: str,
        signature: str,
        slot: int,
        block_time: Optional[int],
        detected_at: str,
        mint: Optional[str],
        deployer_candidate: Optional[str],
        detection_latency_ms: Optional[int],
        status: str,
        pool_state: Optional[str] = None,
    ) -> bool:
        try:
            with closing(sqlite3.connect(self.path, timeout=30.0, isolation_level=None)) as con:
                con.execute('PRAGMA busy_timeout=30000')
                con.execute(
                    '''INSERT INTO launch_candidates
                    (protocol, signature, slot, block_time, detected_at, mint,
                     deployer_candidate, detection_latency_ms, status, pool_state)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        protocol, signature, slot, block_time, detected_at, mint,
                        deployer_candidate, detection_latency_ms, status, pool_state,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False
