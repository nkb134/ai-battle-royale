"""The match loop. §5, §6, §7.

Ordering rules this loop exists to enforce:

  * The clock starts at request dispatch and stops when a legal move is accepted,
    covering network latency and every retry (§6.1).
  * A retry burns clock and earns no increment (§5.3).
  * The `move` event is emitted the instant the move is legal and applied. Analysis
    follows as a separate event and never blocks the stream (§7).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import chess
import chess.pgn

from arena.analysis.annotate import classify, is_brilliant
from arena.analysis.see import hanging_squares
from arena.analysis.stockfish import EnginePool, cp_loss
from arena.config import DATA_DIR, TimeControl
from arena.engine.adjudicate import (
    AdjudicationConfig,
    Adjudicator,
    Outcome,
    flag_fall_outcome,
    natural_outcome,
)
from arena.engine.clock import BLACK, WHITE, Clock, FlagFall
from arena.engine.events import EventStream
from arena.engine.jsonl import JsonlLog
from arena.engine.pacing import PacingConfig, compute_budget
from arena.engine.prompts import MoveParseError, parse_move
from arena.engine.types import ModelAdapter, MoveContext, ProviderError

GAMES_DIR = DATA_DIR / "games"


@dataclass
class MatchSettings:
    time_control: TimeControl
    config_hash: str
    legal_moves_provided: bool = False
    max_retries: int = 2
    on_exhausted: str = "random_legal"
    max_plies: int = 250
    pacing: PacingConfig = field(default_factory=PacingConfig)
    adjudication: AdjudicationConfig = field(default_factory=AdjudicationConfig)
    analyse: bool = True


@dataclass
class MatchResult:
    match_id: str
    outcome: Outcome
    ply_count: int
    pgn: str
    replay_path: str | None
    plies: list[dict]


class Match:
    def __init__(
        self,
        white: ModelAdapter,
        black: ModelAdapter,
        settings: MatchSettings,
        *,
        tokens_per_sec: dict[str, float],
        pool: EnginePool | None = None,
        match_id: str | None = None,
        stream: EventStream | None = None,
        log: JsonlLog | None = None,
        monotonic_ns=None,
    ):
        self.match_id = match_id or uuid.uuid4().hex[:12]
        self.adapters = {WHITE: white, BLACK: black}
        self.settings = settings
        self.tokens_per_sec = tokens_per_sec
        self.pool = pool
        self.board = chess.Board()
        clock_kw = {"monotonic_ns": monotonic_ns} if monotonic_ns else {}
        self.clock = Clock(
            settings.time_control.initial_ms,
            settings.time_control.increment_ms,
            **clock_kw,
        )
        self.adjudicator = Adjudicator(settings.adjudication)
        self.stream = stream or EventStream(self.match_id)
        self.log = log
        self.plies: list[dict] = []
        self.started_at = datetime.now(UTC).isoformat()
        self._analysis_tasks: list[asyncio.Task] = []
        # Set by the analysis coroutine, consumed by the loop. Analysis runs behind the
        # move stream by design (§7), so an adjudication lands a ply or two after the
        # position that triggered it. That lag is the cost of never blocking the board.
        self._pending_adjudication: Outcome | None = None

    # -- helpers ----------------------------------------------------------
    def _side(self) -> str:
        return WHITE if self.board.turn == chess.WHITE else BLACK

    def _budget(self, side: str):
        return compute_budget(
            remaining_ms=self.clock.remaining_ms(side),
            initial_ms=self.clock.initial_ms,
            increment_ms=self.clock.increment_ms,
            move_number=self.board.fullmove_number,
            tokens_per_sec=self.tokens_per_sec[side],
            cfg=self.settings.pacing,
            untimed_cap=self.settings.time_control.token_cap,
        )

    def _clocks(self) -> dict:
        return {
            "clock_white": self.clock.remaining_ms(WHITE),
            "clock_black": self.clock.remaining_ms(BLACK),
        }

    # -- the loop ---------------------------------------------------------
    async def run(self) -> MatchResult:
        self.stream.emit(
            "match_start",
            match_id=self.match_id,
            white=self.adapters[WHITE].name,
            black=self.adapters[BLACK].name,
            time_control=str(self.settings.time_control),
            starting_fen=self.board.fen(),
            # Starting clocks, so a client can show them before the first move rather
            # than parsing the time-control label itself.
            clock_white=self.clock.remaining_ms(WHITE),
            clock_black=self.clock.remaining_ms(BLACK),
            increment_ms=self.clock.increment_ms,
        )
        if self.log:
            self.log.write(
                "match_start",
                match_id=self.match_id,
                white=self.adapters[WHITE].model_string,
                black=self.adapters[BLACK].model_string,
                config_hash=self.settings.config_hash,
                time_control=str(self.settings.time_control),
            )

        outcome: Outcome | None = None
        ply = 0
        try:
            while ply < self.settings.max_plies:
                outcome = natural_outcome(self.board)
                if outcome:
                    break
                ply += 1
                outcome = await self._play_ply(ply)
                if outcome:
                    break
                if self._pending_adjudication is not None:
                    outcome = self._pending_adjudication
                    break
            else:
                outcome = Outcome("1/2-1/2", "adjudicated_ply_cap", True)
        except FlagFall as flag:
            outcome = flag_fall_outcome(flag.side, self.board)
            self.stream.emit("low_time", side=flag.side, remaining_ms=0)
        except ProviderError as err:
            # §13 — abort, and exclude from ratings. Never substitute a move.
            outcome = Outcome("*", "provider_error", False)
            if self.log:
                self.log.write("provider_error", error=str(err))

        assert outcome is not None
        await self._drain_analysis()
        return self._finish(outcome, ply)

    async def _play_ply(self, ply: int) -> Outcome | None:
        side = self._side()
        adapter = self.adapters[side]
        budget = self._budget(side)
        fen_before = self.board.fen()
        clock_before = self.clock.remaining_ms(side)

        if budget.panic:
            self.stream.emit(
                "low_time", side=side, remaining_ms=clock_before or 0
            )

        self.stream.emit(
            "thinking", side=side, token_budget=budget.tokens, **self._clocks()
        )

        move: chess.Move | None = None
        retry_count = 0
        elapsed_total = 0
        reasoning_tokens = None
        forced_random = False

        for attempt in range(self.settings.max_retries + 1):
            ctx = MoveContext(
                fen=fen_before,
                history_san=self._history_san(),
                side_to_move=side,
                own_clock_ms=self.clock.remaining_ms(side),
                opponent_clock_ms=self.clock.remaining_ms(
                    BLACK if side == WHITE else WHITE
                ),
                increment_ms=self.clock.increment_ms,
                token_budget=budget.tokens,
                max_output_tokens=budget.hard_cap(
                    separate_thinking_channel=getattr(adapter, "thinking", False)
                ),
                retry_count=attempt,
                move_number=self.board.fullmove_number,
                panic=budget.panic,
                legal_moves_san=(
                    [self.board.san(m) for m in self.board.legal_moves]
                    if self.settings.legal_moves_provided
                    else None
                ),
            )

            # Clock runs across the whole attempt, including latency (§6.1).
            self.clock.start(side)
            try:
                response = await adapter.move(ctx)
            except ProviderError:
                self.clock.stop(accepted=False)
                raise
            candidate, why = self._interpret(response)
            accepted = candidate is not None
            elapsed_total += self.clock.stop(accepted=accepted)

            if self.log:
                self.log.write(
                    "move_attempt",
                    ply=ply,
                    attempt=attempt,
                    side=side,
                    prompt=_prompt_for(ctx),
                    response=response.text,
                    token_budget=budget.tokens,
                    reasoning_tokens=response.reasoning_tokens,
                    output_tokens=response.output_tokens,
                    truncated=response.truncated,
                    panic=budget.panic,
                    rejected=None if accepted else why,
                    raw=response.raw,
                )

            reasoning_tokens = response.reasoning_tokens
            if accepted:
                move = candidate
                retry_count = attempt
                break
            retry_count = attempt + 1

        if move is None:
            # §5.3 — retries exhausted.
            if self.settings.on_exhausted == "forfeit":
                return Outcome(
                    result="0-1" if side == WHITE else "1-0",
                    termination="illegal_move_forfeit",
                    adjudicated=False,
                )
            move = self._random_legal()
            forced_random = True

        san = self.board.san(move)
        was_capture = self.board.is_capture(move)
        was_pawn_move = self.board.piece_type_at(move.from_square) == chess.PAWN
        board_before = self.board.copy(stack=False)
        self.board.push(move)

        clock_after = self.clock.remaining_ms(side)
        row = {
            "match_id": self.match_id,
            "ply": ply,
            "fen_before": fen_before,
            "move_uci": move.uci(),
            "move_san": san,
            "legal": 1,
            "retry_count": retry_count,
            "cp_before": None,
            "cp_after": None,
            "cp_loss": None,
            "classification": None,
            "clock_ms_before": clock_before,
            "clock_ms_after": clock_after,
            "elapsed_ms": elapsed_total,
            "reasoning_tokens": reasoning_tokens,
            "token_budget": budget.tokens,
            "panic": int(budget.panic),
            "forced_random": forced_random,
        }
        self.plies.append(row)

        # The move event goes out now. Analysis follows separately (§7).
        event = self.stream.emit(
            "move",
            ply=ply,
            san=san,
            uci=move.uci(),
            fen_after=self.board.fen(),
            elapsed_ms=elapsed_total,
            capture=was_capture,
            check=self.board.is_check(),
            retry_count=retry_count,
            panic=budget.panic,
            forced_random=forced_random,
            **self._clocks(),
        )

        if self.settings.analyse and self.pool is not None:
            self._analysis_tasks.append(
                asyncio.create_task(
                    self._analyse(
                        ply=ply,
                        seq=event["seq"],
                        board_before=board_before,
                        board_after=self.board.copy(stack=False),
                        move=move,
                        row=row,
                        mover_is_white=(side == WHITE),
                        was_capture=was_capture,
                        was_pawn_move=was_pawn_move,
                    )
                )
            )
        return None

    def _interpret(self, response) -> tuple[chess.Move | None, str | None]:
        """Turn a raw response into a legal move, or say why it is not one.

        A response with no parseable tag is treated exactly like an illegal move: it
        cost time and it did not produce a move (§5.3).
        """
        if response.error:
            return None, f"error: {response.error}"
        try:
            uci = parse_move(response.text)
        except MoveParseError as exc:
            return None, ("truncated_no_tag" if response.truncated else str(exc))
        try:
            move = chess.Move.from_uci(uci.lower())
        except ValueError:
            # Some models answer in SAN despite the instruction; accept it if legal.
            try:
                move = self.board.parse_san(uci)
            except ValueError:
                return None, f"unparseable: {uci!r}"
        if move not in self.board.legal_moves:
            return None, f"illegal: {uci!r}"
        return move, None

    def _random_legal(self) -> chess.Move:
        import random

        return random.choice(list(self.board.legal_moves))

    def _history_san(self) -> list[str]:
        replay = chess.Board()
        out = []
        for move in self.board.move_stack:
            out.append(replay.san(move))
            replay.push(move)
        return out

    async def _analyse(
        self, *, ply, seq, board_before, board_after, move, row, mover_is_white,
        was_capture, was_pawn_move,
    ) -> None:
        assert self.pool is not None
        before = await self.pool.evaluate(board_before)
        after = await self.pool.evaluate(board_after)
        loss = cp_loss(before.cp, after.cp, mover_is_white)
        label = classify(loss)
        if is_brilliant(
            board_before, move, cp_loss_value=loss, engine_best_uci=before.best_move_uci
        ):
            label = "brilliant"

        row.update(
            cp_before=before.cp, cp_after=after.cp, cp_loss=loss, classification=label
        )
        self.stream.amend(seq, cp_after=after.cp, cp_loss=loss, classification=label)
        self.stream.emit(
            "threats",
            ply=ply,
            best_reply_uci=after.best_move_uci,
            hanging=hanging_squares(board_after, board_after.turn),
            arrows=[after.best_move_uci] if after.best_move_uci else [],
        )

        side_to_move = WHITE if board_after.turn == chess.WHITE else BLACK
        verdict = self.adjudicator.observe(
            ply=ply,
            cp_after=after.cp,
            side_to_move=side_to_move,
            was_capture=was_capture,
            was_pawn_move=was_pawn_move,
        )
        if verdict is not None and self._pending_adjudication is None:
            self._pending_adjudication = verdict

    async def _drain_analysis(self) -> None:
        """Wait for the analysis that trails the move stream.

        A failure here loses annotation for that ply but must never take down a match
        that has already been played. It is logged rather than swallowed, because a
        silently dropped analysis task looks exactly like a clean run.
        """
        if not self._analysis_tasks:
            return
        for task in self._analysis_tasks:
            try:
                await task
            except Exception as exc:  # noqa: BLE001
                if self.log:
                    self.log.write("analysis_error", error=repr(exc))
                else:
                    print(f"analysis task failed: {exc!r}", file=sys.stderr)
        self._analysis_tasks.clear()

    def _finish(self, outcome: Outcome, ply_count: int) -> MatchResult:
        pgn = self._pgn(outcome)
        GAMES_DIR.mkdir(parents=True, exist_ok=True)
        (GAMES_DIR / f"{self.match_id}.pgn").write_text(pgn)

        self.stream.emit(
            "match_end",
            result=outcome.result,
            termination=outcome.termination,
            adjudicated=outcome.adjudicated,
            report_url=f"/report/{self.match_id}",
        )
        replay = self.stream.write_replay(
            {
                "match_id": self.match_id,
                "white": self.adapters[WHITE].name,
                "black": self.adapters[BLACK].name,
                "white_model": self.adapters[WHITE].model_string,
                "black_model": self.adapters[BLACK].model_string,
                "time_control": str(self.settings.time_control),
                "config_hash": self.settings.config_hash,
                "started_at": self.started_at,
                "ended_at": datetime.now(UTC).isoformat(),
                "result": outcome.result,
                "termination": outcome.termination,
                "adjudicated": outcome.adjudicated,
                "ply_count": ply_count,
            }
        )
        if self.log:
            self.log.write(
                "match_end",
                result=outcome.result,
                termination=outcome.termination,
                adjudicated=outcome.adjudicated,
                ply_count=ply_count,
            )
        return MatchResult(
            match_id=self.match_id,
            outcome=outcome,
            ply_count=ply_count,
            pgn=pgn,
            replay_path=str(replay),
            plies=self.plies,
        )

    def _pgn(self, outcome: Outcome) -> str:
        """PGN with the eval in a comment on every ply (§14 Phase 0)."""
        game = chess.pgn.Game()
        game.headers["Event"] = "Arena"
        game.headers["Site"] = "local"
        game.headers["Date"] = self.started_at[:10].replace("-", ".")
        game.headers["White"] = self.adapters[WHITE].name
        game.headers["Black"] = self.adapters[BLACK].name
        game.headers["Result"] = outcome.result
        game.headers["TimeControl"] = str(self.settings.time_control)
        game.headers["Termination"] = outcome.termination
        game.headers["Adjudicated"] = "true" if outcome.adjudicated else "false"
        game.headers["ConfigHash"] = self.settings.config_hash

        node = game
        for row, move in zip(self.plies, self.board.move_stack, strict=False):
            node = node.add_variation(move)
            bits = []
            if row.get("cp_after") is not None:
                bits.append(f"[%eval {row['cp_after'] / 100:.2f}]")
            bits.append(f"[%clk {(row.get('clock_ms_after') or 0) // 1000}s]")
            bits.append(f"[%budget {row['token_budget']}]")
            if row.get("reasoning_tokens") is not None:
                bits.append(f"[%rtok {row['reasoning_tokens']}]")
            if row.get("retry_count"):
                bits.append(f"[%retries {row['retry_count']}]")
            if row.get("panic"):
                bits.append("[%panic]")
            if row.get("forced_random"):
                bits.append("[%forced_random]")
            node.comment = " ".join(bits)
        return str(game)


def _prompt_for(ctx: MoveContext) -> str:
    from arena.engine.prompts import render

    return render(ctx)
