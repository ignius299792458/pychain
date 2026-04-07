"""
db.py — SQLite persistence for PyChain.

Schema:
    blocks      — one row per mined block (full JSON blob + indexed fields)
    peers       — registered peer node URLs

Why SQLite?
    - Zero ops: single file, no server process
    - Python stdlib: no extra dependency
    - Fast enough for thousands of blocks
    - WAL mode gives concurrent read performance

Why JSON blobs for blocks?
    The block structure may evolve (new fields). Storing the full block as
    JSON means the schema never needs migrations for block internals —
    only the indexed columns (hash, index, prev_hash) are relational.
    This is the same approach LevelDB-based chains use: key = block hash,
    value = serialized block.

File location:
    pychain.db  in the project root (set via PYCHAIN_DB_PATH env var)
"""

import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("PYCHAIN_DB_PATH", "pychain.db")


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # concurrent reads don't block writes
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS blocks (
                id           INTEGER PRIMARY KEY,
                block_index  INTEGER NOT NULL UNIQUE,
                hash         TEXT    NOT NULL UNIQUE,
                previous_hash TEXT   NOT NULL,
                timestamp    REAL    NOT NULL,
                nonce        INTEGER NOT NULL,
                merkle_root  TEXT    NOT NULL,
                data         TEXT    NOT NULL    -- full block as JSON
            );

            CREATE INDEX IF NOT EXISTS idx_blocks_hash
                ON blocks(hash);

            CREATE TABLE IF NOT EXISTS peers (
                url TEXT PRIMARY KEY
            );
        """
        )


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


def save_block(block) -> None:
    """Persist a single Block. Called immediately after mining."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO blocks
                (block_index, hash, previous_hash, timestamp, nonce, merkle_root, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                block.index,
                block.hash,
                block.previous_hash,
                block.timestamp,
                block.nonce,
                block.merkle_root,
                json.dumps(block.to_dict()),
            ),
        )


def load_chain() -> list[dict]:
    """
    Load all blocks from DB in order.
    Returns a list of raw dicts — caller reconstructs Block objects.
    Returns [] if DB is empty (first run → genesis block will be created).
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT data FROM blocks ORDER BY block_index ASC"
        ).fetchall()
    return [json.loads(row["data"]) for row in rows]


def get_block_by_hash(hash: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT data FROM blocks WHERE hash = ?", (hash,)).fetchone()
    return json.loads(row["data"]) if row else None


def get_block_by_index(index: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM blocks WHERE block_index = ?", (index,)
        ).fetchone()
    return json.loads(row["data"]) if row else None


def chain_height() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM blocks").fetchone()
    return row["c"]


# ---------------------------------------------------------------------------
# Peers
# ---------------------------------------------------------------------------


def save_peer(url: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO peers (url) VALUES (?)", (url,))


def load_peers() -> set[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT url FROM peers").fetchall()
    return {row["url"] for row in rows}


def delete_peer(url: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM peers WHERE url = ?", (url,))
