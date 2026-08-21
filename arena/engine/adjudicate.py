"""Adjudication. §5.4.

Standard rules are checked first: checkmate, stalemate, threefold, fifty-move,
insufficient material, flag fall. Only then do the eval-based rules apply.

Every adjudicated result is tagged. An adjudication is never presented as a clean
win (§5.4, §15) — that is the caller's obligation too, and the termination string is
what carries it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess


@dataclass(frozen=True)
class AdjudicationConfig:
    resign_cp: int = -900
    resign_plies: int = 6
    draw_cp: int = 50
    draw_plies: int = 30
    max_plies: int = 250

    @classmethod
    def from_dict(cls, d: dict) -> AdjudicationConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Outcome:
    result: str  # "1-0" | "0-1" | "1/2-1/2"
    termination: str
    adjudicated: bool

    @property
    def is_clean(self) -> bool:
        """False for anything adjudicated or flagged. The UI must not dress these up."""
        return not self.adjudicated and self.termination in {
            "checkmate",
            "stalemate",
            "threefold_repetition",
            "fifty_moves",
            "insufficient_material",
        }


def natural_outcome(board: chess.Board) -> Outcome | None:
    """Standard rules, checked before any eval-based adjudication."""
    if board.is_checkmate():
        return Outcome(
            result="0-1" if board.turn == chess.WHITE else "1-0",
            termination="checkmate",
            adjudicated=False,
        )
    if board.is_stalemate():
        return Outcome("1/2-1/2", "stalemate", False)
    if board.is_insufficient_material():
        return Outcome("1/2-1/2", "insufficient_material", False)
    if board.is_fifty_moves():
        return Outcome("1/2-1/2", "fifty_moves", False)
    if board.is_repetition(3):
        return Outcome("1/2-1/2", "threefold_repetition", False)
    return None


def flag_fall_outcome(flagged_side: str, board: chess.Board) -> Outcome:
    """§6.1 — at zero that side loses, unless the opponent cannot possibly mate."""
    opponent = chess.BLACK if flagged_side == "white" else chess.WHITE
    if not _has_mating_material(board, opponent):
        return Outcome("1/2-1/2", "flag_fall_insufficient_material", False)
    return Outcome(
        result="0-1" if flagged_side == "white" else "1-0",
        termination="flag_fall",
        adjudicated=False,
    )


def _has_mating_material(board: chess.Board, color: chess.Color) -> bool:
    if board.pieces(chess.PAWN, color) or board.pieces(chess.ROOK, color):
        return True
    if board.pieces(chess.QUEEN, color):
        return True
    bishops = len(board.pieces(chess.BISHOP, color))
    knights = len(board.pieces(chess.KNIGHT, color))
    return bishops >= 2 or (bishops >= 1 and knights >= 1) or knights >= 3


@dataclass
class Adjudicator:
    """Tracks the streaks that §5.4's eval-based rules need.

    Fed one White-POV eval per ply, after the move is applied.
    """

    cfg: AdjudicationConfig = field(default_factory=AdjudicationConfig)
    _losing_streak: dict[str, int] = field(default_factory=lambda: {"white": 0, "black": 0})
    _quiet_streak: int = 0

    def observe(
        self,
        *,
        ply: int,
        cp_after: int,
        side_to_move: str,
        was_capture: bool,
        was_pawn_move: bool,
    ) -> Outcome | None:
        """Update streaks and return an adjudication if one has now triggered.

        `side_to_move` is whoever is on move in the resulting position, matching
        "eval worse than -900cp for the side to move across 6 consecutive plies".
        """
        # Resignation: from the point of view of the side now to move.
        pov = cp_after if side_to_move == "white" else -cp_after
        if pov < self.cfg.resign_cp:
            self._losing_streak[side_to_move] += 1
        else:
            self._losing_streak[side_to_move] = 0

        # Draw: quiet and level.
        if abs(cp_after) < self.cfg.draw_cp and not was_capture and not was_pawn_move:
            self._quiet_streak += 1
        else:
            self._quiet_streak = 0

        if self._losing_streak[side_to_move] >= self.cfg.resign_plies:
            return Outcome(
                result="0-1" if side_to_move == "white" else "1-0",
                termination="adjudicated_resignation",
                adjudicated=True,
            )
        if self._quiet_streak >= self.cfg.draw_plies:
            return Outcome("1/2-1/2", "adjudicated_draw", True)
        if ply >= self.cfg.max_plies:
            return Outcome("1/2-1/2", "adjudicated_ply_cap", True)
        return None
