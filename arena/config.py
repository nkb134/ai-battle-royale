"""Config loading and config_hash. §11, §13.

Anything that can change a result belongs in arena.yaml, and therefore in config_hash.
Rating pools are keyed on config_hash and are never merged (§11).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "arena.yaml"
LOCAL_CONFIG = REPO_ROOT / "arena.local.yaml"  # gitignored, §16.3
DATA_DIR = REPO_ROOT / "arena" / "data"


@dataclass(frozen=True)
class TimeControl:
    label: str
    initial_ms: int | None
    increment_ms: int
    token_cap: int = 3000

    @property
    def untimed(self) -> bool:
        return self.initial_ms is None

    def __str__(self) -> str:
        if self.untimed:
            return "casual"
        return f"{self.initial_ms // 60000}+{self.increment_ms // 1000}"


def parse_time_control(spec: str, table: dict) -> TimeControl:
    """Accept either a label ("standard") or a chess-style "15+10"."""
    key = spec.strip().lower()
    if key in table:
        entry = table[key]
        return TimeControl(
            label=key,
            initial_ms=entry.get("initial_ms"),
            increment_ms=entry.get("increment_ms", 0),
            token_cap=entry.get("token_cap", 3000),
        )
    if "+" in key:
        minutes, seconds = key.split("+", 1)
        return TimeControl(
            label=key,
            initial_ms=int(minutes) * 60_000,
            increment_ms=int(seconds) * 1_000,
        )
    raise ValueError(f"unknown time control {spec!r}; try one of {sorted(table)} or '15+10'")


class Config:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        base = yaml.safe_load((path or DEFAULT_CONFIG).read_text()) or {}
        if path is None and LOCAL_CONFIG.exists():
            base = _deep_merge(base, yaml.safe_load(LOCAL_CONFIG.read_text()) or {})
        return cls(base)

    # -- sections ---------------------------------------------------------
    @property
    def models(self) -> dict[str, dict]:
        return self.raw.get("models", {})

    def model(self, model_id: str) -> dict:
        try:
            return self.models[model_id]
        except KeyError:
            raise KeyError(
                f"unknown model {model_id!r}; known: {sorted(self.models)}"
            ) from None

    @property
    def match(self) -> dict:
        return self.raw.get("match", {})

    @property
    def pacing(self) -> dict:
        return self.raw.get("pacing", {})

    @property
    def analysis(self) -> dict:
        return self.raw.get("analysis", {})

    @property
    def adjudicate(self) -> dict:
        return self.raw.get("adjudicate", {})

    @property
    def vertex(self) -> dict:
        return self.raw.get("vertex", {})

    def time_control(self, spec: str) -> TimeControl:
        return parse_time_control(spec, self.raw.get("time_controls", {}))

    # -- the hash ---------------------------------------------------------
    def config_hash(self, tc: TimeControl, engine_id: str) -> str:
        """Everything that can change a result, per §11.

        `engine_id` is included on top of the analysis depth: a different Stockfish
        build scores differently, so pools must not merge across engine versions any
        more than across depths.
        """
        payload = {
            "prompt_version": self.raw.get("prompt_version"),
            "legal_moves_provided": self.match.get("legal_moves_provided", False),
            "max_retries": self.match.get("max_retries", 2),
            "on_exhausted": self.match.get("on_exhausted", "random_legal"),
            "max_plies": self.match.get("max_plies", 250),
            "pacing": dict(sorted(self.pacing.items())),
            "adjudicate": dict(sorted(self.adjudicate.items())),
            "analysis_depth": self.analysis.get("depth"),
            "analysis_movetime_ms": self.analysis.get("movetime_ms"),
            "engine_id": engine_id,
            "time_control": str(tc),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out
