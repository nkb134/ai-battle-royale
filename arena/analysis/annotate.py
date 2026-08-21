"""Move classification. §8.2.

Bands are on cp_loss, which is the swing against the mover from the mover's point of
view. Brilliant is flagged separately and is deliberately rare.
"""

from __future__ import annotations

import chess

from arena.analysis.see import see

BANDS = (
    (20, "best"),
    (50, "good"),
    (120, "inaccuracy"),
    (300, "mistake"),
)

COLOURS = {
    "best": "green",
    "good": "neutral",
    "inaccuracy": "yellow",
    "mistake": "orange",
    "blunder": "red",
    "brilliant": "cyan",
}


def classify(cp_loss: int) -> str:
    for ceiling, label in BANDS:
        if cp_loss < ceiling:
            return label
    return "blunder"


def is_brilliant(
    board_before: chess.Board,
    move: chess.Move,
    *,
    cp_loss_value: int,
    engine_best_uci: str | None,
) -> bool:
    """A sacrifice by static exchange evaluation that is still the engine's top choice.

    Both halves matter. A sacrifice the engine dislikes is a blunder, not a brilliancy;
    the engine's top move that risks nothing is merely best. Rare from LLMs, which is
    the point (§8.2).
    """
    if engine_best_uci is None or move.uci() != engine_best_uci:
        return False
    if cp_loss_value > 20:
        return False
    return see(board_before, move) < 0
