"""§5.2, §5.3."""

import pytest

from arena.engine.prompts import MoveParseError, parse_move, render
from arena.engine.types import MoveContext

START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def ctx(**kw):
    base = dict(
        fen=START,
        history_san=[],
        side_to_move="white",
        own_clock_ms=900_000,
        opponent_clock_ms=900_000,
        increment_ms=10_000,
        token_budget=1200,
        retry_count=0,
        move_number=1,
    )
    base.update(kw)
    return MoveContext(**base)


def test_parses_the_tag():
    assert parse_move("thinking...\n<move>e2e4</move>") == "e2e4"


def test_takes_the_last_tag_when_the_model_reconsiders():
    assert parse_move("<move>a2a3</move> wait, better: <move>e2e4</move>") == "e2e4"


def test_ignores_move_shaped_prose_outside_tags():
    """§5.2 — do not regex prose for algebraic notation."""
    with pytest.raises(MoveParseError):
        parse_move("I will play e4, or maybe Nf3. Actually Qxd5 looks strong.")


def test_missing_tag_raises():
    with pytest.raises(MoveParseError):
        parse_move("")


def test_truncated_tag_raises_rather_than_guessing():
    with pytest.raises(MoveParseError):
        parse_move("long reasoning ... <move>e2e4")


def test_prompt_states_both_clocks_and_the_budget():
    p = render(ctx(own_clock_ms=125_000, opponent_clock_ms=61_000, token_budget=777))
    assert "2:05" in p and "1:01" in p and "777" in p


def test_retry_prompt_does_not_hint_at_legal_moves():
    """§5.3 — the retry prompt says only that the move was illegal."""
    p = render(ctx(retry_count=1))
    assert "illegal" in p.lower()
    assert "legal moves available" not in p.lower()


def test_panic_prompt_tells_the_model_to_move_immediately():
    assert "move immediately" in render(ctx(panic=True)).lower()


def test_legal_moves_only_listed_when_the_flag_is_on():
    assert "Legal moves available" not in render(ctx())
    assert "Legal moves available" in render(ctx(legal_moves_san=["e4", "d4"]))


def test_history_is_numbered_san():
    p = render(ctx(history_san=["e4", "e5", "Nf3"]))
    assert "1. e4" in p and "1... e5" in p and "2. Nf3" in p
