"""The match loop end to end. §5.3, §6.1, §7.

Time is injected, so these assert on the loop's behaviour rather than on how fast the
test machine happens to be.
"""

import chess

from arena.config import TimeControl
from arena.engine.adapters.mock import MockAdapter
from arena.engine.match import Match, MatchSettings
from arena.engine.types import MoveContext, ProviderError, RawMoveResponse

STANDARD = TimeControl("test", 60_000, 1_000)


class ScriptedAdapter:
    """Returns a fixed sequence of responses, then plays legally forever."""

    def __init__(self, name, script=(), fallback_legal=True, latency_ms=0,
                 latencies=None, ticker=None):
        self.name = name
        self.model_string = f"{name}-v1"
        self.script = list(script)
        self.fallback_legal = fallback_legal
        # A per-call sequence; the final value repeats once the list runs out.
        self.latencies = list(latencies) if latencies else [latency_ms]
        self.ticker = ticker
        self.calls = []

    def _next_latency(self) -> int:
        return self.latencies[min(len(self.calls) - 1, len(self.latencies) - 1)]

    async def move(self, ctx: MoveContext) -> RawMoveResponse:
        self.calls.append(ctx)
        latency = self._next_latency()
        if self.ticker and latency:
            self.ticker.advance_ms(latency)
        if self.script:
            return self.script.pop(0)
        board = chess.Board(ctx.fen)
        uci = next(iter(board.legal_moves)).uci()
        return RawMoveResponse(
            text=f"<move>{uci}</move>", reasoning_tokens=10, output_tokens=10
        )


class Ticker:
    def __init__(self):
        self.ns = 0

    def __call__(self):
        return self.ns

    def advance_ms(self, ms):
        self.ns += ms * 1_000_000


def settings(**kw):
    base = dict(time_control=STANDARD, config_hash="test", analyse=False)
    base.update(kw)
    return MatchSettings(**base)


def make_match(white, black, ticker=None, **kw):
    return Match(
        white,
        black,
        settings(**kw),
        tokens_per_sec={"white": 100.0, "black": 100.0},
        monotonic_ns=ticker,
    )


async def test_a_full_match_reaches_a_result():
    m = make_match(
        MockAdapter("w", "w-v1", real_time=False, seed=1),
        MockAdapter("b", "b-v1", real_time=False, seed=2),
        max_plies=60,
    )
    result = await m.run()
    assert result.outcome.result in {"1-0", "0-1", "1/2-1/2"}
    assert result.ply_count > 0
    assert result.pgn.startswith("[Event ")


async def test_illegal_move_is_retried_and_the_retry_burns_clock():
    """§5.3 — retries cost time and earn no increment."""
    ticker = Ticker()
    white = ScriptedAdapter(
        "w",
        script=[RawMoveResponse(text="<move>e2e5</move>", reasoning_tokens=5, output_tokens=5)],
        latency_ms=3_000,
        ticker=ticker,
    )
    black = ScriptedAdapter("b", latency_ms=1_000, ticker=ticker)
    m = make_match(white, black, ticker=ticker, max_plies=2)
    await m.run()

    first = m.plies[0]
    assert first["retry_count"] == 1
    # Two dispatches at 3s each, one increment of 1s, from a 60s clock.
    assert first["elapsed_ms"] == 6_000
    assert first["clock_ms_after"] == 60_000 - 6_000 + 1_000


async def test_response_with_no_move_tag_counts_as_illegal():
    """A truncated answer cost time and produced no move. Same treatment (§5.3)."""
    white = ScriptedAdapter(
        "w",
        script=[RawMoveResponse(text="I thought hard.", reasoning_tokens=5,
                                output_tokens=5, truncated=True)],
    )
    m = make_match(white, ScriptedAdapter("b"), max_plies=2)
    await m.run()
    assert m.plies[0]["retry_count"] == 1


async def test_exhausted_retries_fall_back_to_a_random_legal_move():
    bad = RawMoveResponse(text="<move>a1a8</move>", reasoning_tokens=1, output_tokens=1)
    white = ScriptedAdapter("w", script=[bad, bad, bad])
    m = make_match(white, ScriptedAdapter("b"), max_retries=2, max_plies=2)
    await m.run()
    row = m.plies[0]
    assert row["forced_random"] is True
    assert row["retry_count"] == 3
    assert chess.Move.from_uci(row["move_uci"]) in chess.Board().legal_moves


async def test_exhausted_retries_can_forfeit_instead():
    bad = RawMoveResponse(text="<move>a1a8</move>", reasoning_tokens=1, output_tokens=1)
    white = ScriptedAdapter("w", script=[bad, bad, bad])
    m = make_match(white, ScriptedAdapter("b"), max_retries=2,
                   on_exhausted="forfeit", max_plies=2)
    result = await m.run()
    assert result.outcome.result == "0-1"
    assert result.outcome.termination == "illegal_move_forfeit"


async def test_running_out_of_time_ends_the_match_as_a_flag_fall():
    """§6.1 — the clock is the real thing, and it can end the game."""
    ticker = Ticker()
    white = ScriptedAdapter("w", latency_ms=70_000, ticker=ticker)  # over a 60s clock
    m = make_match(white, ScriptedAdapter("b"), ticker=ticker)
    result = await m.run()
    assert result.outcome.termination == "flag_fall"
    assert result.outcome.result == "0-1"
    assert not result.outcome.is_clean


async def test_provider_error_aborts_and_is_never_a_result():
    """§13 — abort as provider_error, never substitute a move."""

    class Broken(ScriptedAdapter):
        async def move(self, ctx):
            raise ProviderError("down")

    result = await make_match(Broken("w"), ScriptedAdapter("b")).run()
    assert result.outcome.termination == "provider_error"
    assert result.outcome.result == "*"


async def test_the_model_is_told_the_budget_it_is_capped_at():
    """§6.2 — told and enforced must be the same number."""
    white = ScriptedAdapter("w")
    m = make_match(white, ScriptedAdapter("b"), max_plies=2)
    await m.run()
    ctx = white.calls[0]
    assert ctx.token_budget == m.plies[0]["token_budget"]


async def test_match_start_carries_the_starting_clocks():
    """§7 — a client should not have to parse the time-control label to show a clock."""
    m = make_match(ScriptedAdapter("w"), ScriptedAdapter("b"), max_plies=2)
    await m.run()
    start = m.stream.events[0]
    assert start["clock_white"] == 60_000
    assert start["clock_black"] == 60_000
    assert start["increment_ms"] == 1_000


async def test_events_are_sequential_and_start_and_end_the_match():
    """§7 — append-only with a monotonic seq."""
    m = make_match(
        MockAdapter("w", "w-v1", real_time=False, seed=3),
        MockAdapter("b", "b-v1", real_time=False, seed=4),
        max_plies=20,
    )
    await m.run()
    seqs = [e["seq"] for e in m.stream.events]
    assert seqs == list(range(1, len(seqs) + 1))
    assert m.stream.events[0]["type"] == "match_start"
    assert m.stream.events[-1]["type"] == "match_end"


async def test_every_move_event_precedes_the_match_end():
    m = make_match(
        MockAdapter("w", "w-v1", real_time=False, seed=5),
        MockAdapter("b", "b-v1", real_time=False, seed=6),
        max_plies=20,
    )
    await m.run()
    types = [e["type"] for e in m.stream.events]
    assert types.count("match_end") == 1
    assert types.index("match_end") == len(types) - 1


async def test_panic_is_recorded_on_the_ply_and_emits_low_time():
    """§6.3 — panic sets the flag on the ply and fires the event."""
    ticker = Ticker()
    # Burn most of White's 60s clock on move one, then move fast, so the second
    # White move is planned under 20% of the starting clock.
    white = ScriptedAdapter("w", latencies=[50_000, 100], ticker=ticker)
    m = make_match(white, ScriptedAdapter("b", latency_ms=0, ticker=ticker),
                   ticker=ticker, max_plies=4)
    await m.run()
    assert any(e["type"] == "low_time" for e in m.stream.events)
    assert m.plies[2]["panic"] == 1
    assert white.calls[-1].panic is True


async def test_pgn_carries_clock_budget_and_termination():
    m = make_match(
        MockAdapter("w", "w-v1", real_time=False, seed=7),
        MockAdapter("b", "b-v1", real_time=False, seed=8),
        max_plies=10,
    )
    result = await m.run()
    assert "[%clk" in result.pgn and "[%budget" in result.pgn
    assert "[Termination " in result.pgn and "[Adjudicated " in result.pgn


async def test_replay_file_is_the_event_list(tmp_path):
    """§16.2 — one format for live and replay, not two."""
    m = make_match(
        MockAdapter("w", "w-v1", real_time=False, seed=9),
        MockAdapter("b", "b-v1", real_time=False, seed=10),
        max_plies=10,
    )
    result = await m.run()
    import json

    data = json.loads(open(result.replay_path).read())
    assert data["events"] == m.stream.events
    assert data["format_version"] == 1
    assert data["result"] == result.outcome.result
