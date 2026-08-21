"""§6.1. Written before the match loop, per §13: test first for anything touching clocks."""

import pytest

from arena.engine.clock import BLACK, WHITE, Clock, FlagFall


class FakeNs:
    """A hand-cranked monotonic clock, so tests measure logic and not the test runner."""

    def __init__(self):
        self.ns = 0

    def __call__(self):
        return self.ns

    def advance_ms(self, ms):
        self.ns += ms * 1_000_000


def test_increment_added_only_on_acceptance():
    t = FakeNs()
    c = Clock(60_000, 5_000, monotonic_ns=t)
    c.start(WHITE)
    t.advance_ms(10_000)
    assert c.stop(accepted=True) == 10_000
    assert c.remaining_ms(WHITE) == 55_000  # 60 - 10 + 5


def test_retry_burns_time_and_earns_no_increment():
    """§5.3 — an illegal move is a real cost, not a free do-over."""
    t = FakeNs()
    c = Clock(60_000, 5_000, monotonic_ns=t)
    c.start(WHITE)
    t.advance_ms(8_000)
    c.stop(accepted=False)
    assert c.remaining_ms(WHITE) == 52_000  # no increment

    c.start(WHITE)
    t.advance_ms(4_000)
    c.stop(accepted=True)
    assert c.remaining_ms(WHITE) == 53_000  # 52 - 4 + 5


def test_opponent_clock_does_not_move():
    t = FakeNs()
    c = Clock(60_000, 5_000, monotonic_ns=t)
    c.start(WHITE)
    t.advance_ms(30_000)
    assert c.remaining_ms(BLACK) == 60_000
    c.stop(accepted=True)
    assert c.remaining_ms(BLACK) == 60_000


def test_flag_fall_raises_and_zeroes():
    t = FakeNs()
    c = Clock(10_000, 5_000, monotonic_ns=t)
    c.start(BLACK)
    t.advance_ms(10_001)
    with pytest.raises(FlagFall) as e:
        c.stop(accepted=True)
    assert e.value.side == BLACK
    assert c.remaining_ms(BLACK) == 0


def test_flag_fall_beats_increment():
    """Running out mid-move flags, even though acceptance would have paid increment."""
    t = FakeNs()
    c = Clock(10_000, 30_000, monotonic_ns=t)
    c.start(WHITE)
    t.advance_ms(11_000)
    with pytest.raises(FlagFall):
        c.stop(accepted=True)


def test_check_flag_detects_overrun_while_request_in_flight():
    t = FakeNs()
    c = Clock(10_000, 0, monotonic_ns=t)
    c.start(WHITE)
    t.advance_ms(9_000)
    assert c.check_flag() is None
    t.advance_ms(2_000)
    assert c.check_flag() == WHITE


def test_remaining_counts_down_live_while_running():
    t = FakeNs()
    c = Clock(60_000, 0, monotonic_ns=t)
    c.start(WHITE)
    t.advance_ms(7_500)
    assert c.remaining_ms(WHITE) == 52_500


def test_untimed_clock_never_flags_but_still_measures():
    """Casual, §6.4 — no clock, but elapsed wall time is still recorded."""
    t = FakeNs()
    c = Clock(None, 0, monotonic_ns=t)
    assert c.untimed
    c.start(WHITE)
    t.advance_ms(120_000)
    assert c.stop(accepted=True) == 120_000
    assert c.remaining_ms(WHITE) is None
    assert c.check_flag() is None


def test_double_start_is_a_bug_not_a_silent_reset():
    c = Clock(60_000, 0)
    c.start(WHITE)
    with pytest.raises(RuntimeError):
        c.start(BLACK)
