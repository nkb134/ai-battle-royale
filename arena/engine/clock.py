"""The chess clock. §6.1.

Fischer increment. The clock starts when the request is dispatched and stops when a
legal move is accepted. Wall clock, including network latency, including every
illegal-move retry. Increment is added only after acceptance.

The server is the sole source of truth for time (§6.1). Nothing here reads a value
supplied by a client, and no method trusts an elapsed time it did not measure itself.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

WHITE = "white"
BLACK = "black"


class FlagFall(Exception):
    """Raised when a side's clock reaches zero. Termination is `flag_fall` (§6.1)."""

    def __init__(self, side: str):
        super().__init__(f"{side} flagged")
        self.side = side


@dataclass
class ClockState:
    white_ms: int | None
    black_ms: int | None
    running: str | None
    started_at_ns: int | None


class Clock:
    """A two-sided Fischer clock, or an untimed clock when `initial_ms` is None.

    Untimed (Casual, §6.4) is a real mode, not a special case bolted on: `remaining`
    returns None, `elapsed` still measures wall time for the log, and nothing can flag.
    """

    def __init__(
        self,
        initial_ms: int | None,
        increment_ms: int = 0,
        *,
        monotonic_ns=time.monotonic_ns,
    ):
        self._untimed = initial_ms is None
        self._initial_ms = initial_ms
        self.increment_ms = 0 if self._untimed else increment_ms
        self._now = monotonic_ns
        self._remaining: dict[str, int | None] = {
            WHITE: initial_ms,
            BLACK: initial_ms,
        }
        self._running: str | None = None
        self._started_at_ns: int | None = None

    @property
    def untimed(self) -> bool:
        return self._untimed

    @property
    def initial_ms(self) -> int | None:
        return self._initial_ms

    def remaining_ms(self, side: str) -> int | None:
        """Remaining time, live. Counts down while that side's clock is running."""
        base = self._remaining[side]
        if base is None:
            return None
        if self._running == side and self._started_at_ns is not None:
            return base - self._elapsed_ms_since_start()
        return base

    def _elapsed_ms_since_start(self) -> int:
        assert self._started_at_ns is not None
        return (self._now() - self._started_at_ns) // 1_000_000

    def start(self, side: str) -> None:
        """Begin charging `side`. Called at request dispatch, before the first token."""
        if self._running is not None:
            raise RuntimeError(f"clock already running for {self._running}")
        self._running = side
        self._started_at_ns = self._now()

    def elapsed_ms(self) -> int:
        """Wall time since `start`, without stopping the clock."""
        if self._running is None:
            return 0
        return self._elapsed_ms_since_start()

    def check_flag(self) -> str | None:
        """Return the flagged side, if the running clock has hit zero. Does not stop it.

        Called while a request is in flight so a match can be abandoned the moment the
        clock runs out, rather than waiting for a slow provider to answer.
        """
        if self._untimed or self._running is None:
            return None
        if (self.remaining_ms(self._running) or 0) <= 0:
            return self._running
        return None

    def stop(self, *, accepted: bool) -> int:
        """Stop the running clock and charge the elapsed wall time.

        `accepted` is True only when a legal move was accepted. Increment is added on
        acceptance alone, so a retry burns time and earns nothing (§5.3).

        Returns elapsed milliseconds. Raises FlagFall if the charge took the side to
        zero or below.
        """
        if self._running is None:
            raise RuntimeError("clock is not running")
        side = self._running
        elapsed = self._elapsed_ms_since_start()
        self._running = None
        self._started_at_ns = None

        if self._untimed:
            return elapsed

        base = self._remaining[side]
        assert base is not None
        base -= elapsed
        if base <= 0:
            self._remaining[side] = 0
            raise FlagFall(side)
        if accepted:
            base += self.increment_ms
        self._remaining[side] = base
        return elapsed

    def state(self) -> ClockState:
        return ClockState(
            white_ms=self.remaining_ms(WHITE),
            black_ms=self.remaining_ms(BLACK),
            running=self._running,
            started_at_ns=self._started_at_ns,
        )
