"""Keep the test suite out of arena/data/.

Match.run() writes a PGN, a replay and a JSONL log as a matter of course. Without this
the suite silently fills the real data directory, and those replays would then be
committed and served on Pages as if they were genuine matches (§16.2, §16.3).
"""

import pytest

import arena.engine.events as events
import arena.engine.jsonl as jsonl
import arena.engine.match as match_module


@pytest.fixture(autouse=True)
def isolate_data_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(match_module, "GAMES_DIR", tmp_path / "games")
    monkeypatch.setattr(events, "REPLAY_DIR", tmp_path / "replays")
    monkeypatch.setattr(jsonl, "LOG_DIR", tmp_path / "logs")
    yield
