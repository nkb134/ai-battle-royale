"""WebSocket fan-out for a running match. §7.

Events are append-only with a monotonic `seq`. A client that joins mid-match gets the
backlog first, then the live tail, so its `seq` sequence has no hole.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field


@dataclass
class Hub:
    """One match, many viewers."""

    events: list[dict] = field(default_factory=list)
    clients: set = field(default_factory=set)
    _loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def sink(self, event: dict) -> None:
        """EventStream sink. Called from the match loop, which is synchronous here."""
        self.events.append(event)
        if self._loop is None:
            return
        for client in list(self.clients):
            self._loop.create_task(self._send(client, event))

    async def _send(self, client, event: dict) -> None:
        try:
            await client.send_text(json.dumps(event))
        except Exception:  # noqa: BLE001 - a dropped viewer must not disturb the match
            self.clients.discard(client)

    async def attach(self, client) -> None:
        """Send the backlog, then subscribe. Order matters: no gap in seq."""
        for event in list(self.events):
            await self._send(client, event)
        self.clients.add(client)

    def detach(self, client) -> None:
        self.clients.discard(client)

    def reset(self) -> None:
        self.events.clear()
