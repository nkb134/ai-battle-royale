"""Opening identification. §8.4.

Names come from the Lichess `chess-openings` tables (CC0), recorded in ASSETS.md.
The opening is the deepest table entry the game actually followed; the ply after it
is where the game left book.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import chess
import chess.pgn

ECO_DIR = Path(__file__).resolve().parent.parent / "data" / "eco"


@dataclass(frozen=True)
class Opening:
    eco: str
    name: str
    ply: int  # plies matched from the table entry

    @property
    def left_book_at_ply(self) -> int:
        """First ply not covered by the book."""
        return self.ply + 1


@lru_cache(maxsize=1)
def _book() -> dict[str, tuple[str, str, int]]:
    """Map an EPD position key to (eco, name, ply_depth).

    Keyed on position rather than move sequence, so transpositions resolve.
    """
    table: dict[str, tuple[str, str, int]] = {}
    for path in sorted(ECO_DIR.glob("*.tsv")):
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                board = chess.Board()
                moves = 0
                try:
                    for token in row["pgn"].split():
                        if token.endswith("."):
                            continue
                        board.push_san(token)
                        moves += 1
                except ValueError:
                    continue
                key = board.epd()
                # Keep the deepest naming for a position.
                existing = table.get(key)
                if existing is None or moves > existing[2]:
                    table[key] = (row["eco"], row["name"], moves)
    return table


def identify(moves_uci: list[str]) -> Opening | None:
    """Deepest book position the game passed through."""
    if not ECO_DIR.exists():
        return None
    book = _book()
    board = chess.Board()
    best: Opening | None = None
    for i, uci in enumerate(moves_uci, start=1):
        try:
            board.push(chess.Move.from_uci(uci))
        except ValueError:
            break
        hit = book.get(board.epd())
        if hit and (best is None or i > best.ply):
            best = Opening(eco=hit[0], name=hit[1], ply=i)
        if i > 30:  # book runs out long before this
            break
    return best
