"""§8.4 — the post-match report, and the panic-versus-calm comparison it exists for."""

import chess

from arena.analysis.eco import identify
from arena.analysis.report import PlyReport, _key_moments, _sentence, _stats


def ply(n, side="white", cp_loss=0, panic=False, retries=0, rtok=None, budget=None,
        forced=False, cls=None):
    from arena.analysis.annotate import classify
    return PlyReport(
        ply=n, san=f"m{n}", uci="e2e4", side=side,
        fen_before=chess.STARTING_FEN, cp_before=0, cp_after=-cp_loss,
        cp_loss=cp_loss, classification=cls or classify(cp_loss),
        best_move_uci="d2d4", clock_ms_after=1000, token_budget=budget,
        reasoning_tokens=rtok, retry_count=retries, panic=panic, forced_random=forced,
    )


def test_acpl_is_the_mean_loss_for_that_side_only():
    plies = [ply(1, "white", 100), ply(2, "black", 400), ply(3, "white", 200)]
    assert _stats(plies, "white").acpl == 150.0
    assert _stats(plies, "black").acpl == 400.0


def test_panic_and_calm_acpl_are_split():
    """The headline comparison of §8.4."""
    plies = [
        ply(1, "white", 50), ply(3, "white", 30),
        ply(5, "white", 400, panic=True), ply(7, "white", 300, panic=True),
    ]
    s = _stats(plies, "white")
    assert s.acpl_calm == 40.0
    assert s.acpl_panic == 350.0
    assert s.panic_plies == 2
    assert s.panic_penalty == 310.0


def test_panic_penalty_is_none_when_the_side_never_panicked():
    s = _stats([ply(1, "white", 50)], "white")
    assert s.acpl_panic is None
    assert s.panic_penalty is None


def test_illegal_moves_count_every_retry_not_every_ply():
    plies = [ply(1, "white", 0, retries=2), ply(3, "white", 0, retries=1)]
    assert _stats(plies, "white").illegal_moves == 3


def test_budget_overrun_counts_only_measured_plies():
    """§6.2 — a model that ignored the budget it was told about."""
    plies = [
        ply(1, "white", 0, rtok=500, budget=300),   # overran
        ply(3, "white", 0, rtok=100, budget=300),   # obeyed
        ply(5, "white", 0, rtok=None, budget=300),  # unmeasured, not counted either way
    ]
    s = _stats(plies, "white")
    assert s.budget_overrun_plies == 1
    assert s.mean_reasoning_tokens == 300.0


def test_blunders_and_forced_randoms_are_counted():
    plies = [ply(1, "white", 500), ply(3, "white", 10, forced=True)]
    s = _stats(plies, "white")
    assert s.blunders == 1
    assert s.forced_random == 1


def test_key_moments_are_the_biggest_swings_worst_first():
    plies = [ply(1, "white", 40), ply(2, "black", 600), ply(3, "white", 250)]
    moments = _key_moments(plies)
    assert [m.swing for m in moments] == [600, 250, 40]


def test_key_moments_skip_plies_that_lost_nothing():
    assert _key_moments([ply(1, "white", 0), ply(2, "black", 0)]) == []


def test_key_moments_are_capped_at_three():
    plies = [ply(i, "white", 100 * i) for i in range(1, 9)]
    assert len(_key_moments(plies)) == 3


def test_a_panic_moment_says_so_in_plain_words():
    text = _sentence(ply(5, "white", 320, panic=True))
    assert "Short of time" in text and "320" in text


def test_a_forced_random_move_is_described_honestly():
    """§15 — never dress up a move the model failed to produce."""
    text = _sentence(ply(5, "white", 400, forced=True))
    assert "random" in text and "failed to produce a legal move" in text


def test_opening_is_named_and_reports_where_book_ended():
    opening = identify(["e2e4", "e7e5", "g1f3", "b8c6", "f1b5"])
    assert opening is not None
    assert opening.eco.startswith("C6")
    assert "Ruy Lopez" in opening.name or "Spanish" in opening.name
    assert opening.left_book_at_ply == opening.ply + 1


def test_an_unbookish_opening_still_resolves_or_returns_none():
    assert identify(["a2a4"]) is not None or identify(["a2a4"]) is None


def test_index_marks_which_matches_have_panic_data(tmp_path):
    """A match where the clock never bit has nothing to say about time pressure, and
    the archive should say so before a reader opens the report (§8.4)."""
    import json

    from arena.engine.events import write_index

    replays = tmp_path / "replays"
    reports = tmp_path / "reports"
    replays.mkdir()
    reports.mkdir()

    (replays / "m1.json").write_text(json.dumps({
        "match_id": "m1", "white": "a", "black": "b", "time_control": "10+5",
        "result": "1-0", "termination": "flag_fall", "adjudicated": False,
        "ply_count": 40, "started_at": "2026-01-01T00:00:00Z", "events": [],
    }))
    (reports / "m1.json").write_text(json.dumps({
        "white_stats": {"panic_plies": 9}, "black_stats": {"panic_plies": 0},
    }))
    # A replay with no report at all.
    (replays / "m2.json").write_text(json.dumps({
        "match_id": "m2", "white": "a", "black": "b", "time_control": "10+5",
        "result": "0-1", "termination": "checkmate", "adjudicated": False,
        "ply_count": 20, "started_at": "2026-01-02T00:00:00Z", "events": [],
    }))

    index = json.loads(write_index(replays).read_text())
    by_id = {m["match_id"]: m for m in index["matches"]}
    assert by_id["m1"]["has_report"] is True
    assert by_id["m1"]["panic_plies"] == 9
    assert by_id["m2"]["has_report"] is False
    assert by_id["m2"]["panic_plies"] is None
