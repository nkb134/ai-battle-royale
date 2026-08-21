"""Post-match report. §8.4.

Regenerated from a stored PGN, so a report can be rebuilt without the database and
without replaying the models. The PGN carries clock, budget, reasoning tokens, retries
and the panic flag in its move comments; the evals are recomputed by Stockfish, which
is what makes `make analyze` a real re-analysis rather than a reformat.

The headline number is **ACPL in panic mode versus the rest of the game**. That
comparison is the payoff of the entire clock system, so it is computed first and given
its own place in the output.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path

import chess
import chess.pgn

from arena.analysis.annotate import classify
from arena.analysis.eco import identify
from arena.analysis.stockfish import EnginePool, cp_loss
from arena.config import DATA_DIR

REPORTS_DIR = DATA_DIR / "reports"
GAMES_DIR = DATA_DIR / "games"

TAG = {
    "clk": re.compile(r"\[%clk (-?\d+)s\]"),
    "budget": re.compile(r"\[%budget (\d+)\]"),
    "rtok": re.compile(r"\[%rtok (\d+)\]"),
    "retries": re.compile(r"\[%retries (\d+)\]"),
}


@dataclass
class PlyReport:
    ply: int
    san: str
    uci: str
    side: str
    fen_before: str
    cp_before: int
    cp_after: int
    cp_loss: int
    classification: str
    best_move_uci: str | None
    clock_ms_after: int | None
    token_budget: int | None
    reasoning_tokens: int | None
    retry_count: int
    panic: bool
    forced_random: bool


@dataclass
class SideStats:
    """§8.4 per-side stats. `acpl_panic` vs `acpl_calm` is the point of the exercise."""

    acpl: float | None = None
    acpl_panic: float | None = None
    acpl_calm: float | None = None
    panic_plies: int = 0
    blunders: int = 0
    mistakes: int = 0
    brilliant: int = 0
    illegal_moves: int = 0
    forced_random: int = 0
    mean_elapsed_ms: float | None = None
    mean_reasoning_tokens: float | None = None
    mean_token_budget: float | None = None
    budget_overrun_plies: int = 0
    moves: int = 0

    @property
    def panic_penalty(self) -> float | None:
        """How much worse the play got under time pressure, in centipawns per move."""
        if self.acpl_panic is None or self.acpl_calm is None:
            return None
        return round(self.acpl_panic - self.acpl_calm, 1)


@dataclass
class KeyMoment:
    ply: int
    san: str
    side: str
    fen_before: str
    cp_before: int
    cp_after: int
    swing: int
    classification: str
    engine_line: str | None
    panic: bool
    sentence: str


@dataclass
class Report:
    match_id: str
    white: str
    black: str
    result: str
    termination: str
    adjudicated: bool
    time_control: str
    config_hash: str
    ply_count: int
    opening_eco: str | None
    opening_name: str | None
    left_book_at_ply: int | None
    eval_graph: list[int] = field(default_factory=list)
    plies: list[PlyReport] = field(default_factory=list)
    key_moments: list[KeyMoment] = field(default_factory=list)
    white_stats: SideStats = field(default_factory=SideStats)
    black_stats: SideStats = field(default_factory=SideStats)


def _tag_int(comment: str, key: str) -> int | None:
    match = TAG[key].search(comment or "")
    return int(match.group(1)) if match else None


async def build(pgn_path: Path, pool: EnginePool) -> Report:
    with pgn_path.open(encoding="utf-8") as fh:
        game = chess.pgn.read_game(fh)
    if game is None:
        raise ValueError(f"no game in {pgn_path}")

    headers = game.headers
    board = game.board()
    plies: list[PlyReport] = []
    moves_uci: list[str] = []

    previous = await pool.evaluate(board)

    node = game
    ply = 0
    while node.variations:
        node = node.variations[0]
        move = node.move
        assert move is not None
        ply += 1
        side = "white" if board.turn == chess.WHITE else "black"
        fen_before = board.fen()
        san = board.san(move)
        moves_uci.append(move.uci())

        board.push(move)
        current = await pool.evaluate(board)
        loss = cp_loss(previous.cp, current.cp, side == "white")
        comment = node.comment or ""

        plies.append(
            PlyReport(
                ply=ply,
                san=san,
                uci=move.uci(),
                side=side,
                fen_before=fen_before,
                cp_before=previous.cp,
                cp_after=current.cp,
                cp_loss=loss,
                classification=classify(loss),
                best_move_uci=previous.best_move_uci,
                clock_ms_after=(
                    None if _tag_int(comment, "clk") is None
                    else _tag_int(comment, "clk") * 1000
                ),
                token_budget=_tag_int(comment, "budget"),
                reasoning_tokens=_tag_int(comment, "rtok"),
                retry_count=_tag_int(comment, "retries") or 0,
                panic="[%panic]" in comment,
                forced_random="[%forced_random]" in comment,
            )
        )
        previous = current

    opening = identify(moves_uci)
    report = Report(
        match_id=pgn_path.stem,
        white=headers.get("White", "?"),
        black=headers.get("Black", "?"),
        result=headers.get("Result", "*"),
        termination=headers.get("Termination", "unknown"),
        adjudicated=headers.get("Adjudicated", "false") == "true",
        time_control=headers.get("TimeControl", "?"),
        config_hash=headers.get("ConfigHash", ""),
        ply_count=len(plies),
        opening_eco=opening.eco if opening else None,
        opening_name=opening.name if opening else None,
        left_book_at_ply=opening.left_book_at_ply if opening else None,
        eval_graph=[p.cp_after for p in plies],
        plies=plies,
        white_stats=_stats(plies, "white"),
        black_stats=_stats(plies, "black"),
        key_moments=_key_moments(plies),
    )
    return report


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 1) if values else None


def _stats(plies: list[PlyReport], side: str) -> SideStats:
    own = [p for p in plies if p.side == side]
    if not own:
        return SideStats()

    panic = [p for p in own if p.panic]
    calm = [p for p in own if not p.panic]

    return SideStats(
        acpl=_mean([p.cp_loss for p in own]),
        acpl_panic=_mean([p.cp_loss for p in panic]),
        acpl_calm=_mean([p.cp_loss for p in calm]),
        panic_plies=len(panic),
        blunders=sum(1 for p in own if p.classification == "blunder"),
        mistakes=sum(1 for p in own if p.classification == "mistake"),
        brilliant=sum(1 for p in own if p.classification == "brilliant"),
        illegal_moves=sum(p.retry_count for p in own),
        forced_random=sum(1 for p in own if p.forced_random),
        mean_reasoning_tokens=_mean(
            [p.reasoning_tokens for p in own if p.reasoning_tokens is not None]
        ),
        mean_token_budget=_mean(
            [p.token_budget for p in own if p.token_budget is not None]
        ),
        # §6.2 — how often the model blew through the budget it was told about.
        budget_overrun_plies=sum(
            1
            for p in own
            if p.reasoning_tokens is not None
            and p.token_budget is not None
            and p.reasoning_tokens > p.token_budget
        ),
        moves=len(own),
    )


def _sentence(p: PlyReport) -> str:
    """One plain sentence about what happened. No jargon beyond the piece names."""
    mover = p.side.capitalize()
    best = p.best_move_uci
    if p.classification == "brilliant":
        return f"{mover} found {p.san}, a sacrifice that is also the engine's top move."
    if p.forced_random:
        return (
            f"{mover} failed to produce a legal move and {p.san} was played at random, "
            f"costing {p.cp_loss} centipawns."
        )
    if p.panic:
        return (
            f"Short of time, {mover} played {p.san} and gave up {p.cp_loss} centipawns"
            + (f"; the engine wanted {best}." if best else ".")
        )
    if p.cp_loss >= 300:
        return (
            f"{mover} blundered with {p.san}, losing {p.cp_loss} centipawns"
            + (f" where {best} held." if best else ".")
        )
    return (
        f"{mover} played {p.san}, giving up {p.cp_loss} centipawns"
        + (f"; {best} was better." if best else ".")
    )


def _key_moments(plies: list[PlyReport], limit: int = 3) -> list[KeyMoment]:
    ranked = sorted(plies, key=lambda p: p.cp_loss, reverse=True)[:limit]
    return [
        KeyMoment(
            ply=p.ply,
            san=p.san,
            side=p.side,
            fen_before=p.fen_before,
            cp_before=p.cp_before,
            cp_after=p.cp_after,
            swing=p.cp_loss,
            classification=p.classification,
            engine_line=p.best_move_uci,
            panic=p.panic,
            sentence=_sentence(p),
        )
        for p in ranked
        if p.cp_loss > 0
    ]


def write(report: Report, directory: Path | None = None) -> Path:
    directory = directory or REPORTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report.match_id}.json"
    path.write_text(json.dumps(asdict(report), indent=1))
    return path
