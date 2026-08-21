"""Stockfish over UCI. §8.1.

Sign convention, and it is the one thing in this project most likely to be silently
wrong: **every eval is stored in centipawns from White's point of view.** python-chess
hands back a PovScore relative to the side to move; call `.white()` before scoring.
Mates clamp to +/-10000.

Process hygiene: engines are opened in a pool and always closed in a `finally`, or the
processes leak and quietly eat every core on the machine (§13, known traps).
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from dataclasses import dataclass

import chess
import chess.engine

MATE_SCORE = 10_000

# Evaluations are clamped to this before a cp_loss is taken (§8.2, §8.4).
# A mate score is +/-10000, so without a cap a single lost position dominates the
# mean and ACPL stops describing the play: a random-mover match scored 6853. The
# figure is a summary of decision quality, and past a rook down the position is
# already decided, so further drops say nothing more about the move.
ACPL_CAP = 1_000


@dataclass(frozen=True)
class AnalysisConfig:
    depth: int = 18
    movetime_ms: int = 200
    threads: int = 1
    hash_mb: int = 128

    @classmethod
    def from_dict(cls, d: dict) -> AnalysisConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @property
    def limit(self) -> chess.engine.Limit:
        # "depth 18 or 200ms, whichever comes first" (§8.1)
        return chess.engine.Limit(depth=self.depth, time=self.movetime_ms / 1000.0)


def stockfish_path() -> str:
    path = shutil.which("stockfish")
    if not path:
        raise RuntimeError("stockfish not found on PATH. See `make setup`.")
    return path


def engine_id(path: str | None = None) -> str:
    """The engine's self-reported name, folded into config_hash.

    Rating pools must not merge across engine versions any more than across depths.
    """
    path = path or stockfish_path()
    engine = chess.engine.SimpleEngine.popen_uci(path)
    try:
        return engine.id.get("name", "unknown")
    finally:
        engine.quit()


def cp_from_white(score: chess.engine.PovScore) -> int:
    """The whole sign convention, in one place, used by everything that stores an eval."""
    return score.white().score(mate_score=MATE_SCORE)


def clamp_mate(cp: int) -> int:
    return max(-MATE_SCORE, min(MATE_SCORE, cp))


@dataclass
class PlyEval:
    cp: int  # from White's point of view, always
    best_move_uci: str | None
    depth: int | None
    mate_in: int | None


class EnginePool:
    """A fixed set of persistent engines, handed out one at a time.

    Async because analysis must never block the move stream (§7). Use as a context
    manager; `close()` is idempotent and runs on every exit path.
    """

    def __init__(self, size: int = 2, cfg: AnalysisConfig | None = None, path: str | None = None):
        self.cfg = cfg or AnalysisConfig()
        self._path = path or stockfish_path()
        self._size = size
        self._pool: asyncio.Queue[chess.engine.SimpleEngine] = asyncio.Queue()
        self._engines: list[chess.engine.SimpleEngine] = []
        self._open = False

    async def __aenter__(self) -> EnginePool:
        await self.open()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def open(self) -> None:
        if self._open:
            return
        loop = asyncio.get_running_loop()
        for _ in range(self._size):
            engine = await loop.run_in_executor(
                None, chess.engine.SimpleEngine.popen_uci, self._path
            )
            with contextlib.suppress(chess.engine.EngineError):
                engine.configure({"Threads": self.cfg.threads, "Hash": self.cfg.hash_mb})
            self._engines.append(engine)
            self._pool.put_nowait(engine)
        self._open = True

    async def close(self) -> None:
        if not self._open:
            return
        self._open = False
        loop = asyncio.get_running_loop()
        for engine in self._engines:
            with contextlib.suppress(Exception):
                await loop.run_in_executor(None, engine.quit)
        self._engines.clear()
        while not self._pool.empty():
            self._pool.get_nowait()

    @contextlib.asynccontextmanager
    async def acquire(self):
        engine = await self._pool.get()
        try:
            yield engine
        finally:
            self._pool.put_nowait(engine)

    async def evaluate(self, board: chess.Board) -> PlyEval:
        """Evaluate a position. Returns centipawns from White's point of view."""
        if board.is_game_over():
            return _terminal_eval(board)

        loop = asyncio.get_running_loop()
        async with self.acquire() as engine:
            info = await loop.run_in_executor(
                None, lambda: engine.analyse(board, self.cfg.limit)
            )
        score = info["score"]
        pv = info.get("pv") or []
        mate = score.white().mate()
        return PlyEval(
            cp=clamp_mate(cp_from_white(score)),
            best_move_uci=pv[0].uci() if pv else None,
            depth=info.get("depth"),
            mate_in=mate,
        )


def _terminal_eval(board: chess.Board) -> PlyEval:
    outcome = board.outcome(claim_draw=True)
    if outcome is None or outcome.winner is None:
        return PlyEval(cp=0, best_move_uci=None, depth=None, mate_in=0)
    cp = MATE_SCORE if outcome.winner == chess.WHITE else -MATE_SCORE
    return PlyEval(cp=cp, best_move_uci=None, depth=None, mate_in=0)


def cp_loss(cp_before: int, cp_after: int, mover_is_white: bool) -> int:
    """Swing against the mover, from the mover's point of view (§8.2).

    Both inputs are White-POV, and both are clamped to +/-ACPL_CAP first. Never
    negative: a move cannot beat the engine's best.
    """
    before = max(-ACPL_CAP, min(ACPL_CAP, cp_before))
    after = max(-ACPL_CAP, min(ACPL_CAP, cp_after))
    loss = before - after if mover_is_white else after - before
    return max(0, loss)
