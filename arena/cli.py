"""Headless entry points. §2 commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime

from arena.analysis.stockfish import AnalysisConfig, EnginePool, engine_id
from arena.config import Config
from arena.db import store
from arena.engine.adapters import build_adapter
from arena.engine.adjudicate import AdjudicationConfig
from arena.engine.events import write_index
from arena.engine.jsonl import JsonlLog
from arena.engine.match import Match, MatchSettings
from arena.engine.pacing import PacingConfig, will_likely_flag
from arena.engine.types import MoveContext


def _settings(cfg: Config, tc_spec: str, eng_id: str, *, analyse: bool) -> MatchSettings:
    tc = cfg.time_control(tc_spec)
    return MatchSettings(
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
        analyse=analyse,
    )


def _tokens_per_sec(cfg: Config, model_id: str) -> float:
    spec = cfg.model(model_id)
    tps = spec.get("tokens_per_sec")
    if not tps:
        raise SystemExit(
            f"{model_id} has no measured tokens_per_sec. Run `make calibrate MODEL={model_id}`. "
            "§6.3 requires it measured, never guessed."
        )
    return float(tps)


async def run_match(args) -> int:
    cfg = Config.load()
    eng_id = engine_id() if args.analyse else "none"
    settings = _settings(cfg, args.tc, eng_id, analyse=args.analyse)

    for model_id in (args.white, args.black):
        spec = cfg.model(model_id)
        if not settings.time_control.untimed and will_likely_flag(
            initial_ms=settings.time_control.initial_ms,
            increment_ms=settings.time_control.increment_ms,
            tokens_per_sec=spec.get("tokens_per_sec"),
        ):
            print(
                f"warning: {model_id} is likely to flag at {settings.time_control} (§6.4)",
                file=sys.stderr,
            )

    def mock_extras(offset: int) -> dict:
        extra: dict = {"seed": getattr(args, "seed", 0) + offset}
        if getattr(args, "latency_scale", 1.0) != 1.0:
            extra["latency_scale"] = args.latency_scale
        return extra

    def make(model_id: str, offset: int):
        spec = cfg.model(model_id)
        extras = mock_extras(offset) if spec.get("provider") == "mock" else {}
        return build_adapter(model_id, spec, vertex=cfg.vertex, **extras)

    # Different seeds per side, or both would draw the same move from the same position.
    white = make(args.white, 0)
    black = make(args.black, 1000)

    conn = store.init_db()
    for model_id in (args.white, args.black):
        store.upsert_model(conn, model_id, cfg.model(model_id))

    pool = None
    log = None
    try:
        if args.analyse:
            pool = EnginePool(size=2, cfg=AnalysisConfig.from_dict(cfg.analysis))
            await pool.open()

        match = Match(
            white,
            black,
            settings,
            tokens_per_sec={
                "white": _tokens_per_sec(cfg, args.white),
                "black": _tokens_per_sec(cfg, args.black),
            },
            pool=pool,
        )
        log = JsonlLog(match.match_id)
        match.log = log

        store.insert_match(
            conn,
            {
                "id": match.match_id,
                "white": args.white,
                "black": args.black,
                "time_control": str(settings.time_control),
                "config_hash": settings.config_hash,
                "started_at": match.started_at,
            },
        )
        result = await match.run()

        for row in result.plies:
            store.insert_ply(conn, {k: v for k, v in row.items() if k != "forced_random"})
        store.finish_match(
            conn,
            match.match_id,
            ended_at=datetime.now(UTC).isoformat(),
            result=result.outcome.result,
            termination=result.outcome.termination,
            ply_count=result.ply_count,
        )
        write_index()

        tag = " (adjudicated)" if result.outcome.adjudicated else ""
        print(
            f"{match.match_id}  {args.white} vs {args.black}  "
            f"{result.outcome.result}  {result.outcome.termination}{tag}  "
            f"{result.ply_count} plies"
        )
        return 0
    finally:
        if pool is not None:
            await pool.close()
        if log is not None:
            log.close()
        conn.close()


async def calibrate(args) -> int:
    """Measure tokens/sec over 20 sample positions and store a rolling median (§6.3)."""
    cfg = Config.load()
    spec = cfg.model(args.model)
    adapter = build_adapter(args.model, spec, vertex=cfg.vertex)

    import chess

    board = chess.Board()
    samples: list[float] = []
    for i in range(args.samples):
        ctx = MoveContext(
            fen=board.fen(),
            history_san=[],
            side_to_move="white" if board.turn else "black",
            own_clock_ms=900_000,
            opponent_clock_ms=900_000,
            increment_ms=10_000,
            token_budget=800,
            retry_count=0,
            move_number=board.fullmove_number,
        )
        start = time.monotonic()
        resp = await adapter.move(ctx)
        elapsed = time.monotonic() - start
        tokens = resp.output_tokens or resp.reasoning_tokens
        if tokens and elapsed > 0:
            samples.append(tokens / elapsed)
            print(f"  sample {i + 1}/{args.samples}: {tokens} tok in {elapsed:.1f}s")
        legal = list(board.legal_moves)
        if legal:
            board.push(legal[i % len(legal)])

    if not samples:
        raise SystemExit("no usable samples; the provider returned no token counts")
    median = statistics.median(samples)
    print(f"\n{args.model}: tokens_per_sec = {median:.1f}  (n={len(samples)})")
    print(f"Set this in arena.yaml under models.{args.model}.tokens_per_sec")
    return 0


def analyze(args) -> int:
    print(f"analyze {args.game}: Phase 1, not yet built (§14)")
    return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="arena")
    sub = parser.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("match", help="run a headless match")
    m.add_argument("--white", required=True)
    m.add_argument("--black", required=True)
    m.add_argument("--tc", default="standard")
    m.add_argument("--repeat", type=int, default=1)
    m.add_argument("--no-analyse", dest="analyse", action="store_false")
    m.add_argument(
        "--latency-scale",
        type=float,
        default=1.0,
        help="mock adapters only: compress simulated latency (§ test affordance)",
    )
    m.add_argument(
        "--seed",
        type=int,
        default=0,
        help="mock adapters only: base seed. --repeat increments it per match, so a "
        "repeated run plays different games instead of the same one ten times.",
    )

    c = sub.add_parser("calibrate", help="measure tokens/sec (§6.3)")
    c.add_argument("--model", required=True)
    c.add_argument("--samples", type=int, default=20)

    a = sub.add_parser("analyze", help="re-run analysis on a stored game")
    a.add_argument("--game", required=True)

    sub.add_parser("index", help="rebuild the replay index for Pages")

    args = parser.parse_args(argv)

    if args.cmd == "match":
        codes = []
        base_seed = args.seed
        for i in range(args.repeat):
            args.seed = base_seed + i * 7919  # a prime stride, so runs do not overlap
            codes.append(asyncio.run(run_match(args)))
        return max(codes)
    if args.cmd == "calibrate":
        return asyncio.run(calibrate(args))
    if args.cmd == "analyze":
        return analyze(args)
    if args.cmd == "index":
        path = write_index()
        print(json.loads(path.read_text())["matches"].__len__(), "replays indexed")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
