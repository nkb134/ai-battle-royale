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
    #: Thinking tokens alone, when the provider breaks them out. None when it does not.
    reasoning_tokens: int | None
    #: The visible reply, or everything generated when the provider bundles the two.
    output_tokens: int | None
    #: Everything generated, thinking included. Set explicitly by adapters whose
    #: provider already bundles thinking into output_tokens, so it is not counted
    #: twice. Left None where the sum below is correct.
    total_output_tokens: int | None = None
    truncated: bool = False
    error: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def generated_tokens(self) -> int | None:
        """Every token the provider generated for this move.

        This, not the visible reply, is what latency is proportional to (§6.2), so
        this is what calibration divides by elapsed time (§6.3).
        """
        if self.total_output_tokens is not None:
            return self.total_output_tokens
        if self.reasoning_tokens is None and self.output_tokens is None:
            return None
        return (self.reasoning_tokens or 0) + (self.output_tokens or 0)


class ModelAdapter(Protocol):
    name: str
    model_string: str  # exact pinned dated version, never "latest"

    async def move(self, ctx: MoveContext) -> RawMoveResponse: ...


class ProviderError(RuntimeError):
    """Raised after backoff is exhausted. Aborts the match as provider_error (§13)."""
