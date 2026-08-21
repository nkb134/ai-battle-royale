"""Adapter plumbing shared by every provider. §5.1, §13.

Provider errors get exponential backoff, 3 attempts, then the match aborts as
`provider_error` and is excluded from ratings. A move is never substituted outside the
§5.3 retry policy.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from arena.engine.types import ProviderError

T = TypeVar("T")

MAX_ATTEMPTS = 3
BASE_DELAY_S = 1.0


async def with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    what: str,
    attempts: int = MAX_ATTEMPTS,
    sleep=asyncio.sleep,
) -> T:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - provider SDKs raise their own trees
            last = exc
            if attempt == attempts - 1:
                break
            await sleep(BASE_DELAY_S * (2**attempt) * (0.5 + random.random()))
    raise ProviderError(f"{what} failed after {attempts} attempts: {last}") from last


class BaseAdapter:
    """Holds the identity fields every adapter needs. Subclasses implement `move`."""

    def __init__(self, name: str, model_string: str, *, thinking: bool = False, **kw):
        self.name = name
        self.model_string = model_string
        self.thinking = thinking
        self.options = kw

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name} {self.model_string}>"
