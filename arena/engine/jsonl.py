"""Per-match JSONL log. §4.

Every prompt and every raw response, never truncated, never into SQLite. Gitignored,
because the repo is public (§16.3).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from arena.config import DATA_DIR

LOG_DIR = DATA_DIR / "logs"


class JsonlLog:
    def __init__(self, match_id: str, directory: Path | None = None):
        directory = directory or LOG_DIR
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{match_id}.jsonl"
        self._fh = self.path.open("a", encoding="utf-8")

    def write(self, kind: str, **payload) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "kind": kind,
            **payload,
        }
        self._fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> JsonlLog:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
