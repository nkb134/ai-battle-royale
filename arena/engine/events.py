"""The §7 event stream, and the §16.2 replay file.

One event list serves both. Live, these are pushed over the WebSocket; recorded, the
same list is written to data/replays/<match_id>.json so the Pages client can replay it
through the same reducer. Writing a second format, or letting the two drift, defeats
the point (§16.2).

Append-only, monotonic `seq`, so a client can spot a gap and refetch.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arena.config import DATA_DIR

REPLAY_DIR = DATA_DIR / "replays"
REPLAY_FORMAT_VERSION = 1


@dataclass
class EventStream:
    """Collects §7 events and fans them out to any number of live sinks."""

    match_id: str
    events: list[dict] = field(default_factory=list)
    sinks: list[Callable[[dict], None]] = field(default_factory=list)
    _seq: int = 0

    def emit(self, type_: str, **payload: Any) -> dict:
        self._seq += 1
        event = {"seq": self._seq, "type": type_, **payload}
        self.events.append(event)
        for sink in self.sinks:
            sink(event)
        return event

    def amend(self, seq: int, **payload: Any) -> None:
        """Attach late analysis to an already-emitted event.

        Only ever used before the replay is written. A live client gets the same
        information as a separate `threats` event instead, because the live stream is
        append-only and never rewrites history (§7).
        """
        for event in self.events:
            if event["seq"] == seq:
                event.update(payload)
                return
        raise KeyError(f"no event with seq {seq}")

    def write_replay(self, header: dict, directory: Path | None = None) -> Path:
        directory = directory or REPLAY_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.match_id}.json"
        path.write_text(
            json.dumps(
                {
                    "format_version": REPLAY_FORMAT_VERSION,
                    **header,
                    "events": self.events,
                },
                indent=1,
            )
        )
        return path


def write_index(directory: Path | None = None) -> Path:
    """A manifest of every replay, so the static Pages client can list them.

    Pages has no directory listing, so without this the client has nothing to read.
    """
    directory = directory or REPLAY_DIR
    directory.mkdir(parents=True, exist_ok=True)
    reports_dir = directory.parent / "reports"
    entries = []
    for path in sorted(directory.glob("*.json")):
        if path.name == "index.json":
            continue
        data = json.loads(path.read_text())
        # A match only has a report once `make analyze` has run. Surfacing whether one
        # exists — and whether it has any panic plies at all — saves opening a report
        # to find out there is nothing in it.
        report_path = reports_dir / path.name
        has_report = report_path.exists()
        panic_plies = None
        if has_report:
            try:
                report = json.loads(report_path.read_text())
                panic_plies = (
                    report.get("white_stats", {}).get("panic_plies", 0)
                    + report.get("black_stats", {}).get("panic_plies", 0)
                )
            except (json.JSONDecodeError, OSError):
                has_report = False
        entries.append(
            {
                "match_id": data.get("match_id"),
                "has_report": has_report,
                "panic_plies": panic_plies,
                "white": data.get("white"),
                "black": data.get("black"),
                "time_control": data.get("time_control"),
                "result": data.get("result"),
                "termination": data.get("termination"),
                "adjudicated": data.get("adjudicated"),
                "ply_count": data.get("ply_count"),
                "started_at": data.get("started_at"),
            }
        )
    entries.sort(key=lambda e: e.get("started_at") or "", reverse=True)
    index = directory / "index.json"
    index.write_text(json.dumps({"matches": entries}, indent=1))
    return index
