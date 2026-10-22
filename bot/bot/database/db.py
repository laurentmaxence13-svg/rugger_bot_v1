import sqlite3
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
    status TEXT NOT NULL
);
'''

class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(self.path) as con:
            con.executescript(SCHEMA)

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
    ) -> bool:
        try:
            with sqlite3.connect(self.path) as con:
                con.execute(
                    '''INSERT INTO launch_candidates
                    (protocol, signature, slot, block_time, detected_at, mint,
                     deployer_candidate, detection_latency_ms, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        protocol, signature, slot, block_time, detected_at, mint,
                        deployer_candidate, detection_latency_ms, status,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False
