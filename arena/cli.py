"""Headless entry points. §2 commands."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

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
            max_output_tokens=800 + 512,
            separate_thinking_channel=bool(spec.get("thinking", False)),
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

    # Median, not mean: one stalled request should not drag the figure down (§6.3).
    median = statistics.median(samples)
    previous = spec.get("tokens_per_sec")
    if previous:
        # Rolling: smooth against the last measurement so one noisy run cannot swing
        # the pacing controller, while a genuine throughput change still lands within
        # a couple of recalibrations. Providers change throughput without saying so
        # (§6.3), so this must track real drift rather than pin the old figure.
        median = 0.6 * median + 0.4 * float(previous)
    print(f"\n{args.model}: tokens_per_sec = {median:.1f}  (n={len(samples)})")
    if previous:
        print(f"  previous: {previous}")

    if args.write:
        _write_tokens_per_sec(args.model, round(median, 1))
        print(f"  written to arena.yaml under models.{args.model}.tokens_per_sec")
    else:
        print(f"  not written (--no-write). Set it under models.{args.model}")
    return 0


def _write_tokens_per_sec(model_id: str, value: float) -> None:
    """Patch one scalar in arena.yaml, preserving comments and ordering.

    A round-trip through yaml.safe_load would strip every comment in the file, and
    those comments carry the reasoning behind the config. So edit the line in place.
    """
    from arena.config import DEFAULT_CONFIG

    lines = DEFAULT_CONFIG.read_text().splitlines(keepends=True)
    in_models = False
    in_model = False
    for i, line in enumerate(lines):
        if line.startswith("models:"):
            in_models = True
            continue
        if in_models and line and not line[0].isspace():
            break  # left the models block
        if in_models and line.strip().rstrip(":") == model_id and line.startswith("  "):
            in_model = True
            continue
        if in_model:
            if line.strip().startswith("tokens_per_sec:"):
                indent = line[: len(line) - len(line.lstrip())]
                lines[i] = f"{indent}tokens_per_sec: {value}\n"
                DEFAULT_CONFIG.write_text("".join(lines))
                return
            # A new sibling model started before we found the key.
            if line.strip() and not line.startswith("    "):
                break
    raise SystemExit(f"could not find models.{model_id}.tokens_per_sec in arena.yaml")


async def analyze(args) -> int:
    """Rebuild a full report from a stored PGN (§14 Phase 1 definition of done)."""
    from arena.analysis import report as report_mod

    cfg = Config.load()
    path = report_mod.GAMES_DIR / f"{Path(args.game).name}.pgn"
    if not path.exists():
        raise SystemExit(f"no PGN at {path}")

    pool = EnginePool(size=2, cfg=AnalysisConfig.from_dict(cfg.analysis))
    try:
        await pool.open()
        built = await report_mod.build(path, pool)
    finally:
        await pool.close()

    out = report_mod.write(built)
    w, b = built.white_stats, built.black_stats
    print(f"{built.match_id}  {built.white} vs {built.black}  {built.result}")
    if built.opening_name:
        print(f"  opening: {built.opening_eco} {built.opening_name} "
              f"(left book at ply {built.left_book_at_ply})")
    for name, stats in ((built.white, w), (built.black, b)):
        print(f"  {name}:")
        print(f"    ACPL {stats.acpl}  blunders {stats.blunders}  "
              f"illegal {stats.illegal_moves}")
        if stats.panic_plies:
            print(f"    ACPL in panic {stats.acpl_panic} vs {stats.acpl_calm} "
                  f"otherwise  ({stats.panic_plies} panic plies, "
                  f"penalty {stats.panic_penalty}cp)")
        else:
            print("    never entered panic mode")
        if stats.mean_reasoning_tokens is not None:
            print(f"    mean reasoning {stats.mean_reasoning_tokens} tok "
                  f"of {stats.mean_token_budget} budget, "
                  f"{stats.budget_overrun_plies} overruns")
        side = "white" if name == built.white else "black"
        rj = built.rejections.get(side)
        if rj:
            print(f"    attempts {rj['total_attempts']}: {rj['accepted']} accepted, "
                  f"{rj['illegal']} illegal, {rj['unparseable']} unparseable, "
                  f"{rj['truncated_no_tag']} truncated")
            if rj["relabelled"]:
                print(f"    relabelled from the log: {rj['relabelled']}")
    print(f"  written to {out}")
    return 0


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
    c.add_argument("--no-write", dest="write", action="store_false",
                   help="print the measurement without updating arena.yaml")

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
        return asyncio.run(analyze(args))
    if args.cmd == "index":
        path = write_index()
        print(json.loads(path.read_text())["matches"].__len__(), "replays indexed")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
