"""Move notation parsing, and why a response was refused. §5.2, §5.3.

Lives apart from the match loop because analysis needs it too: a stored log can be
re-read long after the match, and its rejections re-derived under the current parser
rather than whatever the parser said at the time (§4 — the log is the record, and the
record is raw, so the interpretation belongs here rather than baked into it).
"""

from __future__ import annotations

from enum import StrEnum

import chess


class Rejection(StrEnum):
    """Why a response did not yield a move. These are different findings.

    `ILLEGAL` says the model named a move that is not available — a chess mistake.
    `UNPARSEABLE` says it did not name a move at all — a format failure. Collapsing
    the two makes a model look like it cannot follow instructions when it can, or
    the reverse.
    """

    ILLEGAL = "illegal"
    AMBIGUOUS = "ambiguous"
    UNPARSEABLE = "unparseable"
    TRUNCATED_NO_TAG = "truncated_no_tag"
    NO_TAG = "no_tag"
    ERROR = "error"


def parse_notation(board: chess.Board, text: str) -> tuple[chess.Move | None, str]:
    """Accept UCI, SAN or long algebraic, and say why when refusing.

    The prompt asks for UCI and usually gets it, but models also write `Nc6`,
    `Nb8c6` and `rc7e7`. Each names exactly one move, so refusing them would make
    this a test of format compliance rather than of chess, which is not what the
    retry policy is for (§5.3).

    The move returned is not guaranteed legal — only that it was named. The caller
    checks legality, because a move can be perfectly well formed and still not
    available.
    """
    candidate = text.strip().rstrip("+#")
    if not candidate:
        return None, Rejection.UNPARSEABLE

    for attempt in (candidate, candidate.lower()):
        try:
            return chess.Move.from_uci(attempt), ""
        except ValueError:
            pass

    # Long algebraic: a piece letter in front of an otherwise valid UCI move.
    # Case-insensitive, because models write both `Rc7e7` and `rc7e7`. Tried after
    # plain UCI so a real UCI move like `b1c3` is never read as a bishop move.
    if len(candidate) >= 5 and candidate[0].upper() in "KQRBNP":
        try:
            return chess.Move.from_uci(candidate[1:].lower()), ""
        except ValueError:
            pass

    try:
        return board.parse_san(candidate), ""
    except chess.IllegalMoveError:
        return None, Rejection.ILLEGAL
    except chess.AmbiguousMoveError:
        return None, Rejection.AMBIGUOUS
    except chess.InvalidMoveError:
        return None, Rejection.UNPARSEABLE
    except ValueError:
        return None, Rejection.UNPARSEABLE
