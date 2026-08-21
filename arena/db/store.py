"""SQLite persistence. §4.

WAL mode, always. Raw prompts and raw responses never come here — they go to
data/logs/<match_id>.jsonl, untruncated (§4).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from arena.config import DATA_DIR

SCHEMA = Path(__file__).with_name("schema.sql")
DB_PATH = DATA_DIR / "arena.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | None = None) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA.read_text())
    return conn


def upsert_model(conn: sqlite3.Connection, model_id: str, spec: dict) -> None:
    conn.execute(
        """INSERT INTO models (id, provider, model_string, display_name, face_id,
                               palette, voice, tokens_per_sec, active)
           VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
             provider=excluded.provider, model_string=excluded.model_string,
             display_name=excluded.display_name, tokens_per_sec=excluded.tokens_per_sec,
             active=excluded.active""",
        (
            model_id,
            spec.get("provider", ""),
            spec.get("model_string", ""),
            spec.get("display_name", model_id),
            spec.get("face_id"),
            spec.get("palette"),
            spec.get("voice"),
            spec.get("tokens_per_sec"),
            int(spec.get("active", True)),
        ),
    )


def insert_match(conn: sqlite3.Connection, row: dict) -> None:
    conn.execute(
        """INSERT INTO matches (id, white, black, time_control, config_hash, started_at)
           VALUES (:id, :white, :black, :time_control, :config_hash, :started_at)""",
        row,
    )


def finish_match(conn: sqlite3.Connection, match_id: str, **kw) -> None:
    conn.execute(
        """UPDATE matches SET ended_at=:ended_at, result=:result,
                              termination=:termination, ply_count=:ply_count
           WHERE id=:id""",
        {"id": match_id, **kw},
    )


PLY_COLUMNS = (
    "match_id, ply, fen_before, move_uci, move_san, legal, retry_count, cp_before, "
    "cp_after, cp_loss, classification, clock_ms_before, clock_ms_after, elapsed_ms, "
    "reasoning_tokens, token_budget, panic"
)


def insert_ply(conn: sqlite3.Connection, row: dict) -> None:
    placeholders = ", ".join(f":{c.strip()}" for c in PLY_COLUMNS.split(","))
    conn.execute(f"INSERT INTO plies ({PLY_COLUMNS}) VALUES ({placeholders})", row)


def update_ply_analysis(conn: sqlite3.Connection, match_id: str, ply: int, **kw) -> None:
    """Analysis lands after the move, never blocking it (§7)."""
    sets = ", ".join(f"{k}=:{k}" for k in kw)
    conn.execute(
        f"UPDATE plies SET {sets} WHERE match_id=:match_id AND ply=:ply",
        {"match_id": match_id, "ply": ply, **kw},
    )


if __name__ == "__main__":
    if "--init" in sys.argv:
        conn = init_db()
        print(f"initialised {DB_PATH}")
        conn.close()
