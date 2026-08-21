"""Shared types for the match engine. See §5.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class MoveContext:
    """Everything a model is allowed to see, and nothing else (§5.1).

    The adapter never sees the eval, the rating, or the opponent's reasoning.
    """

    fen: str
    history_san: list[str]
    side_to_move: str  # "white" | "black"
    own_clock_ms: int | None  # None in Casual, which has no clock
    opponent_clock_ms: int | None
    increment_ms: int
    token_budget: int
    # The request's max-output ceiling for this move. Not the same as token_budget:
    # see Budget.hard_cap for why the two differ by model type (§6.2).
    max_output_tokens: int
    # True when the provider reasons in a channel of its own. Such a model is asked
    # for the tag alone, because its visible reply shares the request ceiling with
    # its thinking and prose there buys nothing.
    separate_thinking_channel: bool
    retry_count: int
    move_number: int
    panic: bool = False
    legal_moves_san: list[str] | None = None  # only when legal_moves_provided (§5.3)


@dataclass
class RawMoveResponse:
    """What an adapter hands back. The raw text is logged untruncated (§4)."""

    text: str
    reasoning_tokens: int | None
    output_tokens: int | None
    truncated: bool = False
    error: str | None = None
    raw: dict = field(default_factory=dict)


class ModelAdapter(Protocol):
    name: str
    model_string: str  # exact pinned dated version, never "latest"

    async def move(self, ctx: MoveContext) -> RawMoveResponse: ...


class ProviderError(RuntimeError):
    """Raised after backoff is exhausted. Aborts the match as provider_error (§13)."""
