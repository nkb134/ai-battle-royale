"""Re-derive why each response was refused, from the raw log. §4, §5.3.

The JSONL log is the record and is written raw and never rewritten, so the label a
response was given at match time is frozen with whatever the parser understood then.
That label is an interpretation, not an observation, and interpretations improve: a
real match recorded 30 ordinary illegal SAN moves as parser failures because
`_interpret` collapsed three distinct python-chess exceptions into one.

So the labels are recomputed here, at analysis time, under the current parser. The
observations the recomputation needs — the position and the model's exact words — are
both in the log already: the FEN is quoted in the prompt.

Nothing in this module writes to the log.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import chess

from arena.config import DATA_DIR
from arena.engine.notation import Rejection, parse_notation
from arena.engine.prompts import MoveParseError, parse_move

LOG_DIR = DATA_DIR / "logs"

# The prompt quotes the position it was built from, which is what makes a rejection
# re-derivable. If the prompt template stops doing that, this returns nothing rather
# than guessing.
FEN_IN_PROMPT = re.compile(r"Position \(FEN\):\s*\n(\S.*)")


@dataclass
class RejectionBreakdown:
    """Per-side counts of why responses were refused, recomputed."""

    illegal: int = 0
    ambiguous: int = 0
    unparseable: int = 0
    truncated_no_tag: int = 0
    no_tag: int = 0
    error: int = 0
    accepted: int = 0
    total_attempts: int = 0
    #: Labels that changed between the log and this recomputation, for auditing.
    relabelled: dict[str, int] = field(default_factory=dict)

    @property
    def refused(self) -> int:
        return self.total_attempts - self.accepted

    def as_dict(self) -> dict:
        return {
            "illegal": self.illegal,
            "ambiguous": self.ambiguous,
            "unparseable": self.unparseable,
            "truncated_no_tag": self.truncated_no_tag,
            "no_tag": self.no_tag,
            "error": self.error,
            "accepted": self.accepted,
            "refused": self.refused,
            "total_attempts": self.total_attempts,
            "relabelled": dict(sorted(self.relabelled.items())),
        }


def classify_attempt(record: dict) -> str:
    """Re-derive one attempt's outcome. Returns "" when the move was accepted."""
    if record.get("raw", {}).get("error") or record.get("error"):
        return Rejection.ERROR

    match = FEN_IN_PROMPT.search(record.get("prompt", "") or "")
    if not match:
        # Cannot re-derive without the position; fall back to what was recorded.
        recorded = record.get("rejected")
        return recorded.split(":")[0] if recorded else ""

    board = chess.Board(match.group(1).strip())

    try:
        named = parse_move(record.get("response", "") or "")
    except MoveParseError:
        return (
            Rejection.TRUNCATED_NO_TAG
            if record.get("truncated")
            else Rejection.NO_TAG
        )

    move, why = parse_notation(board, named)
    if move is None:
        return why
    return "" if move in board.legal_moves else Rejection.ILLEGAL


def breakdown(match_id: str, directory: Path | None = None) -> dict[str, RejectionBreakdown]:
    """Recompute the rejection breakdown per side for a stored match.

    Returns an empty mapping when no log is present. `make analyze` must still work
    from a PGN alone (§14 Phase 1), so a missing log degrades rather than fails.
    """
    path = (directory or LOG_DIR) / f"{match_id}.jsonl"
    if not path.exists():
        return {}

    out = {"white": RejectionBreakdown(), "black": RejectionBreakdown()}
    changed: dict[str, Counter] = {"white": Counter(), "black": Counter()}

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("kind") != "move_attempt":
                continue
            side = record.get("side")
            if side not in out:
                continue

            stats = out[side]
            stats.total_attempts += 1
            derived = classify_attempt(record)

            if derived == "":
                stats.accepted += 1
            else:
                setattr(stats, derived, getattr(stats, derived, 0) + 1)

            recorded = (record.get("rejected") or "").split(":")[0]
            if recorded != derived:
                changed[side][f"{recorded or 'accepted'} -> {derived or 'accepted'}"] += 1

    for side, stats in out.items():
        stats.relabelled = dict(changed[side])
    return out
