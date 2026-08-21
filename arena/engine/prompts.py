"""Versioned prompt templates and the move parser. §5.2.

The prompt states the position, both clocks, the increment and the token allowance,
then asks for reasoning followed by a single move in a tag. Parse the last `<move>`
tag. Never regex prose for algebraic notation (§5.2).
"""

from __future__ import annotations

import re

from arena.engine.types import MoveContext

PROMPT_VERSION = "PROMPT_V1"

MOVE_TAG = re.compile(r"<move>\s*([^<\s]+)\s*</move>", re.IGNORECASE)


class MoveParseError(ValueError):
    """No parseable `<move>` tag. Treated exactly like an illegal move (§5.3)."""


def parse_move(text: str) -> str:
    """Return the contents of the *last* `<move>` tag.

    Last, not first: a model that reconsiders mid-reasoning should be taken at its
    final word. Anything outside a tag is ignored, however move-shaped it looks.
    """
    matches = MOVE_TAG.findall(text or "")
    if not matches:
        raise MoveParseError("no <move> tag in response")
    return matches[-1].strip()


def _fmt_clock(ms: int | None) -> str:
    if ms is None:
        return "no limit"
    if ms <= 0:
        return "0:00"
    total = ms // 1000
    return f"{total // 60}:{total % 60:02d}"


PROMPT_V1 = """You are playing a game of chess as {side}.

Position (FEN):
{fen}

Moves so far:
{history}

Clocks:
  You: {own_clock}
  Opponent: {opp_clock}
  Increment: {increment}s per move

Token allowance for this move: {token_budget} tokens.
Stay inside it. Time spent generating is time taken off your clock, and if your clock
reaches zero you lose the game on time.
{extra}
Think about the position, then give your move as a UCI string inside a move tag, like:

<move>e2e4</move>

The move tag must be the last thing you write."""

RETRY_SUFFIX = """

Your previous move was illegal. Give a different, legal move.
That attempt has already cost you time on your clock."""

PANIC_SUFFIX = """

You are low on time. Move immediately with minimal reasoning."""

LEGAL_MOVES_SUFFIX = """

Legal moves available: {legal}"""


def render(ctx: MoveContext) -> str:
    """Build the prompt for one move.

    The retry line says only that the move was illegal. It must not hint at what is
    legal (§5.3).
    """
    extra = ""
    if ctx.panic:
        extra += PANIC_SUFFIX
    if ctx.legal_moves_san:
        extra += LEGAL_MOVES_SUFFIX.format(legal=", ".join(ctx.legal_moves_san))
    if ctx.retry_count:
        extra += RETRY_SUFFIX

    history = " ".join(
        f"{i // 2 + 1}.{'' if i % 2 == 0 else '..'} {san}"
        for i, san in enumerate(ctx.history_san)
    )

    return PROMPT_V1.format(
        side=ctx.side_to_move,
        fen=ctx.fen,
        history=history or "(none, this is the opening move)",
        own_clock=_fmt_clock(ctx.own_clock_ms),
        opp_clock=_fmt_clock(ctx.opponent_clock_ms),
        increment=ctx.increment_ms // 1000,
        token_budget=ctx.token_budget,
        extra=extra + ("\n" if extra else ""),
    )
