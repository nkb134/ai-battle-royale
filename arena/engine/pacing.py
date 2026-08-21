"""Clock -> token budget. §6.3.

A model cannot decide to think faster. Its latency is roughly
`tokens_generated / throughput + overhead`, so "play faster" means exactly one thing:
generate fewer reasoning tokens (§6.2).

The budget is enforced twice and both are needed. It is *told* to the model in the
prompt, and it is *enforced* as a cap on the request. The second is what actually works.
Log both `token_budget` and the observed `reasoning_tokens` so it stays visible which
models respond to being told, which is a result in its own right.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PacingConfig:
    reserve_fraction: float = 0.10
    min_tokens: int = 120  # enough for a bare move with no reasoning
    max_tokens: int = 4000
    panic_fraction: float = 0.20
    panic_tokens: int = 250
    critical_fraction: float = 0.10
    move_tag_headroom: int = 96

    @classmethod
    def from_dict(cls, d: dict) -> PacingConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Budget:
    """The outcome of a pacing decision for one move."""

    tokens: int  # what the model is told, and what its reasoning is capped at
    panic: bool
    critical: bool
    expected_moves_left: int
    time_per_move_ms: int | None
    headroom: int = 96

    @property
    def hard_cap(self) -> int:
        """The request's max output ceiling.

        Headroom above the reasoning budget so the closing `<move>` tag still fits
        (§6.2). Capping a thinking model at exactly `tokens` truncates it mid-thought
        and produces a parse failure, which is a different thing from playing fast.
        """
        return self.tokens + self.headroom


def compute_budget(
    *,
    remaining_ms: int | None,
    initial_ms: int | None,
    increment_ms: int,
    move_number: int,
    tokens_per_sec: float,
    cfg: PacingConfig,
    untimed_cap: int = 3000,
) -> Budget:
    """Convert remaining clock into a token budget.

    Untimed (Casual, §6.4) has no clock to divide, so it takes a flat per-move cap and
    can never panic. Everything else follows §6.3 exactly.
    """
    if remaining_ms is None or initial_ms is None:
        return Budget(
            tokens=min(untimed_cap, cfg.max_tokens),
            panic=False,
            critical=False,
            expected_moves_left=0,
            time_per_move_ms=None,
            headroom=cfg.move_tag_headroom,
        )

    if tokens_per_sec <= 0:
        raise ValueError("tokens_per_sec must be measured and positive (§6.3)")

    expected_moves_left = max(12, 40 - move_number)
    reserve_ms = initial_ms * cfg.reserve_fraction
    time_per_move_ms = (remaining_ms - reserve_ms) / expected_moves_left + increment_ms

    raw = time_per_move_ms * tokens_per_sec / 1000.0
    tokens = int(max(cfg.min_tokens, min(cfg.max_tokens, raw)))

    # Panic mode (§6.3). Below 20% of the starting clock the budget is hard-capped and
    # the model is told to move immediately; below 10% it gets the bare minimum.
    fraction_left = remaining_ms / initial_ms
    critical = fraction_left < cfg.critical_fraction
    panic = fraction_left < cfg.panic_fraction

    if critical:
        tokens = cfg.min_tokens
    elif panic:
        tokens = min(tokens, cfg.panic_tokens)

    return Budget(
        tokens=tokens,
        panic=panic,
        critical=critical,
        expected_moves_left=expected_moves_left,
        time_per_move_ms=int(time_per_move_ms),
        headroom=cfg.move_tag_headroom,
    )


def will_likely_flag(
    *,
    initial_ms: int,
    increment_ms: int,
    tokens_per_sec: float | None,
    typical_tokens: int = 1200,
    expected_moves: int = 35,
) -> bool:
    """Setup-screen warning for a likely flag fall (§6.4).

    Computed from calibration data, never guessed. An uncalibrated model returns True,
    because an unmeasured model is exactly the case the warning exists for.
    """
    if not tokens_per_sec or tokens_per_sec <= 0:
        return True
    seconds_per_move = typical_tokens / tokens_per_sec
    budget_seconds = (initial_ms / 1000.0) + (increment_ms / 1000.0) * expected_moves
    return seconds_per_move * expected_moves > budget_seconds
