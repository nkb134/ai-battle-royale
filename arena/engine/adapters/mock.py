"""A deterministic local adapter. No network, no cost, no provider variance.

This is what the Phase 0 done criteria are exercised against, and what the test suite
uses. It is deliberately capable of playing badly, playing illegally and running slow,
because those are the paths the match loop has to survive.
"""

from __future__ import annotations

import asyncio
import random

import chess

from arena.engine.adapters.base import BaseAdapter
from arena.engine.types import MoveContext, RawMoveResponse


class MockAdapter(BaseAdapter):
    """Plays a seeded random legal move, at a simulated throughput.

    `illegal_rate` and `no_tag_rate` inject the failure modes the retry policy exists
    for. `tokens_per_sec` makes the simulated latency respond to the token budget, so
    the pacing controller and flag fall are genuinely exercised.
    """

    def __init__(
        self,
        name: str,
        model_string: str,
        *,
        tokens_per_sec: float = 120.0,
        illegal_rate: float = 0.05,
        no_tag_rate: float = 0.02,
        obedience: float = 1.0,
        seed: int = 0,
        real_time: bool = True,
        latency_scale: float = 1.0,
        **kw,
    ):
        super().__init__(name, model_string, **kw)
        self.tokens_per_sec = tokens_per_sec
        self.illegal_rate = illegal_rate
        self.no_tag_rate = no_tag_rate
        self.obedience = obedience  # 1.0 respects the budget; >1 overshoots it
        self.real_time = real_time
        # Compresses simulated latency so a full match can be watched end to end in a
        # reasonable time. Only the mock has this. A real provider cannot fake its own
        # throughput, and the clock measures real wall time either way.
        self.latency_scale = latency_scale
        self._rng = random.Random(seed)

    async def move(self, ctx: MoveContext) -> RawMoveResponse:
        board = chess.Board(ctx.fen)
        legal = list(board.legal_moves)

        tokens = max(1, int(ctx.token_budget * self.obedience))
        truncated = tokens > ctx.token_budget
        tokens = min(tokens, ctx.token_budget)

        if self.real_time:
            await asyncio.sleep(tokens / self.tokens_per_sec / self.latency_scale)

        roll = self._rng.random()
        if roll < self.no_tag_rate:
            return RawMoveResponse(
                text="I have thought about this at length but forgot the tag.",
                reasoning_tokens=tokens,
                output_tokens=tokens,
                truncated=truncated,
            )

        if roll < self.no_tag_rate + self.illegal_rate:
            uci = self._illegal_uci(board)
        else:
            uci = self._rng.choice(legal).uci()

        return RawMoveResponse(
            text=f"Considering the position.\n<move>{uci}</move>",
            reasoning_tokens=tokens,
            output_tokens=tokens,
            truncated=truncated,
        )

    def _illegal_uci(self, board: chess.Board) -> str:
        legal = {m.uci() for m in board.legal_moves}
        for _ in range(40):
            a = chess.SQUARE_NAMES[self._rng.randrange(64)]
            b = chess.SQUARE_NAMES[self._rng.randrange(64)]
            if a != b and a + b not in legal:
                return a + b
        return "a1a1"
