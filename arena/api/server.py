"""Local FastAPI server for live mode. §16.1.

Local only, and deliberately so. The engine, the Stockfish process and the database
never leave the machine; GitHub Pages serves recordings, not this (§16).
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from arena.analysis.stockfish import AnalysisConfig, EnginePool, engine_id
from arena.api.ws import Hub
from arena.config import DATA_DIR, Config
from arena.engine.adapters import build_adapter
from arena.engine.adjudicate import AdjudicationConfig
from arena.engine.events import EventStream
from arena.engine.jsonl import JsonlLog
from arena.engine.match import Match, MatchSettings
from arena.engine.pacing import PacingConfig, will_likely_flag

app = FastAPI(title="Arena")

# The Pages-hosted client is a different origin, and live mode is the whole reason it
# would talk to this process (§16.1). Nothing here is authenticated because nothing
# here is meant to be reachable from outside the machine — bind to localhost only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HUB = Hub()
STATE: dict = {"running": False, "task": None}


@app.get("/api/models")
def models() -> JSONResponse:
    cfg = Config.load()
    return JSONResponse(
        {
            "models": [
                {
                    "id": model_id,
                    "display_name": spec.get("display_name", model_id),
                    "provider": spec.get("provider"),
                    "tokens_per_sec": spec.get("tokens_per_sec"),
                    "calibrated": bool(spec.get("tokens_per_sec")),
                    "active": bool(spec.get("active", True)),
                }
                for model_id, spec in cfg.models.items()
            ],
            "time_controls": cfg.raw.get("time_controls", {}),
        }
    )


@app.get("/api/replays")
def replays() -> JSONResponse:
    index = DATA_DIR / "replays" / "index.json"
    if not index.exists():
        return JSONResponse({"matches": []})
    return JSONResponse(content=_read_json(index))


@app.get("/api/replays/{match_id}")
def replay(match_id: str) -> JSONResponse:
    # Only ever look inside the replay directory, whatever the caller sends.
    path = (DATA_DIR / "replays" / f"{Path(match_id).name}.json").resolve()
    root = (DATA_DIR / "replays").resolve()
    if root not in path.parents or not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(content=_read_json(path))


@app.post("/api/match")
async def start_match(payload: dict) -> JSONResponse:
    if STATE["running"]:
        return JSONResponse({"error": "a match is already running"}, status_code=409)

    cfg = Config.load()
    white_id = payload.get("white")
    black_id = payload.get("black")
    tc_spec = payload.get("time_control", "standard")

    try:
        white_spec = cfg.model(white_id)
        black_spec = cfg.model(black_id)
        tc = cfg.time_control(tc_spec)
    except (KeyError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    for model_id, spec in ((white_id, white_spec), (black_id, black_spec)):
        if not spec.get("tokens_per_sec"):
            return JSONResponse(
                {
                    "error": f"{model_id} is uncalibrated. Run `make calibrate "
                    f"MODEL={model_id}`; §6.3 requires a measured tokens_per_sec."
                },
                status_code=400,
            )

    warnings = [
        f"{model_id} is likely to flag at {tc}"
        for model_id, spec in ((white_id, white_spec), (black_id, black_spec))
        if not tc.untimed
        and will_likely_flag(
            initial_ms=tc.initial_ms,
            increment_ms=tc.increment_ms,
            tokens_per_sec=spec.get("tokens_per_sec"),
        )
    ]

    HUB.reset()
    HUB.bind(asyncio.get_running_loop())
    STATE["running"] = True
    STATE["task"] = asyncio.create_task(
        _run(cfg, white_id, black_id, tc_spec, white_spec, black_spec)
    )
    return JSONResponse({"started": True, "warnings": warnings})


async def _run(cfg, white_id, black_id, tc_spec, white_spec, black_spec) -> None:
    pool = None
    log = None
    try:
        eng_id = engine_id()
        tc = cfg.time_control(tc_spec)
        settings = MatchSettings(
            time_control=tc,
            config_hash=cfg.config_hash(tc, eng_id),
            legal_moves_provided=cfg.match.get("legal_moves_provided", False),
            max_retries=cfg.match.get("max_retries", 2),
            on_exhausted=cfg.match.get("on_exhausted", "random_legal"),
            max_plies=cfg.match.get("max_plies", 250),
            pacing=PacingConfig.from_dict(cfg.pacing),
            adjudication=AdjudicationConfig.from_dict(
                {**cfg.adjudicate, "max_plies": cfg.match.get("max_plies", 250)}
            ),
        )
        pool = EnginePool(size=2, cfg=AnalysisConfig.from_dict(cfg.analysis))
        await pool.open()

        match = Match(
            build_adapter(white_id, white_spec, vertex=cfg.vertex),
            build_adapter(black_id, black_spec, vertex=cfg.vertex),
            settings,
            tokens_per_sec={
                "white": float(white_spec["tokens_per_sec"]),
                "black": float(black_spec["tokens_per_sec"]),
            },
            pool=pool,
        )
        stream = EventStream(match.match_id)
        stream.sinks.append(HUB.sink)
        match.stream = stream
        log = JsonlLog(match.match_id)
        match.log = log
        await match.run()
    finally:
        STATE["running"] = False
        if pool is not None:
            await pool.close()
        if log is not None:
            log.close()


@app.websocket("/ws")
async def ws(socket: WebSocket) -> None:
    await socket.accept()
    await HUB.attach(socket)
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        HUB.detach(socket)


def _read_json(path: Path):
    import json

    return json.loads(path.read_text())


def main() -> None:
    import uvicorn

    # localhost only. This process is not meant to be reachable from the network.
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        main()
