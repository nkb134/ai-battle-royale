"""§6.2, §6.3 — what counts as a generated token.

Latency is roughly `tokens_generated / throughput`, and thinking tokens are generated.
Calibration that counts only the visible reply divides part of the output by all of the
time, and understates throughput by however much the model was thinking. Measured on a
real Gemini 2.5 Pro match that was 3.4x: 18.3 tok/s calibrated against 61.8 observed.

An undersized tokens_per_sec makes the pacing controller hand out budgets far smaller
than the clock allows, so the model finishes each move well inside its slice and the
clock never drains. The whole point of §6.3 is that this number is measured, so
measuring it wrongly is worse than not measuring it.
"""

from arena.engine.types import RawMoveResponse


def test_total_defaults_to_the_sum_when_reasoning_is_broken_out():
    """Gemini reports thoughts and candidates separately; both were generated."""
    r = RawMoveResponse(text="", reasoning_tokens=800, output_tokens=10)
    assert r.generated_tokens == 810


def test_total_is_not_double_counted_when_the_provider_bundles_thinking():
    """Anthropic bills thinking inside output_tokens, so summing would double it."""
    r = RawMoveResponse(
        text="", reasoning_tokens=None, output_tokens=850, total_output_tokens=850
    )
    assert r.generated_tokens == 850


def test_an_explicit_total_always_wins():
    r = RawMoveResponse(
        text="", reasoning_tokens=800, output_tokens=10, total_output_tokens=805
    )
    assert r.generated_tokens == 805


def test_visible_only_still_works_for_a_model_that_does_not_think():
    r = RawMoveResponse(text="", reasoning_tokens=None, output_tokens=300)
    assert r.generated_tokens == 300


def test_nothing_measured_yields_none_rather_than_a_guess():
    """§13 — count from the usage field, never estimate."""
    r = RawMoveResponse(text="", reasoning_tokens=None, output_tokens=None)
    assert r.generated_tokens is None
