"""§6.3."""

from arena.engine.pacing import PacingConfig, compute_budget, will_likely_flag

CFG = PacingConfig()


def budget(remaining_ms, move_number=10, tps=50.0, initial=900_000, inc=10_000):
    return compute_budget(
        remaining_ms=remaining_ms,
        initial_ms=initial,
        increment_ms=inc,
        move_number=move_number,
        tokens_per_sec=tps,
        cfg=CFG,
    )


def test_formula_matches_spec():
    # expected_moves_left = max(12, 40-10) = 30
    # reserve = 90_000; tpm = (900_000-90_000)/30 + 10_000 = 37_000ms
    # tokens = 37_000 * 50 / 1000 = 1850
    b = budget(900_000)
    assert b.expected_moves_left == 30
    assert b.time_per_move_ms == 37_000
    assert b.tokens == 1850
    assert not b.panic


def test_expected_moves_left_floors_at_twelve():
    assert budget(900_000, move_number=90).expected_moves_left == 12


def test_budget_clamps_to_max():
    assert budget(900_000, tps=500.0).tokens == CFG.max_tokens


def test_budget_clamps_to_min():
    assert budget(95_000, tps=0.5).tokens == CFG.min_tokens


def test_panic_below_twenty_percent():
    b = budget(170_000)  # 18.9% of 900_000
    assert b.panic and not b.critical
    assert b.tokens <= CFG.panic_tokens


def test_critical_below_ten_percent_takes_the_floor():
    b = budget(80_000)  # 8.9%
    assert b.critical and b.panic
    assert b.tokens == CFG.min_tokens


def test_panic_boundary_is_exclusive_at_exactly_twenty_percent():
    assert not budget(180_000).panic
    assert budget(179_999).panic


def test_hard_cap_leaves_room_for_the_move_tag():
    """§6.2 — truncating at exactly the budget would eat the closing tag."""
    b = budget(900_000)
    assert b.hard_cap == b.tokens + CFG.move_tag_headroom


def test_untimed_uses_flat_cap_and_never_panics():
    b = compute_budget(
        remaining_ms=None,
        initial_ms=None,
        increment_ms=0,
        move_number=5,
        tokens_per_sec=50.0,
        cfg=CFG,
        untimed_cap=3000,
    )
    assert b.tokens == 3000
    assert not b.panic and not b.critical


def test_uncalibrated_model_always_warns():
    """§6.4 — computed from calibration data, never guessed."""
    assert will_likely_flag(initial_ms=900_000, increment_ms=10_000, tokens_per_sec=None)


def test_fast_model_on_standard_does_not_warn():
    assert not will_likely_flag(initial_ms=900_000, increment_ms=10_000, tokens_per_sec=120.0)


def test_slow_model_on_quick_warns():
    assert will_likely_flag(initial_ms=600_000, increment_ms=5_000, tokens_per_sec=8.0)
