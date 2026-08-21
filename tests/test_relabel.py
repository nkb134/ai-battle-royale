"""§4, §5.3 — re-deriving rejection labels from the raw log.

The log is written raw and never rewritten, so a label recorded at match time is
frozen with whatever the parser understood then. These tests pin the recomputation.
"""

import json

import chess

from arena.analysis.relabel import breakdown, classify_attempt

START = chess.STARTING_FEN


def record(response, fen=START, side="white", truncated=False, rejected=None, **kw):
    return {
        "kind": "move_attempt",
        "side": side,
        "prompt": f"Position (FEN):\n{fen}\n\nMoves so far:\n(none)",
        "response": response,
        "truncated": truncated,
        "rejected": rejected,
        "raw": {},
        **kw,
    }


def test_a_legal_move_is_accepted():
    assert classify_attempt(record("<move>e2e4</move>")) == ""


def test_well_formed_san_that_is_illegal_here_is_illegal_not_unparseable():
    """The bug this module exists for."""
    assert classify_attempt(record("<move>Ke7</move>")) == "illegal"
    assert classify_attempt(record("<move>O-O</move>")) == "illegal"


def test_genuine_nonsense_is_still_unparseable():
    assert classify_attempt(record("<move>Ngf6xa8</move>")) == "unparseable"


def test_illegal_uci_is_illegal():
    assert classify_attempt(record("<move>e2e5</move>")) == "illegal"


def test_a_missing_tag_is_distinguished_from_a_truncated_one():
    assert classify_attempt(record("I forgot the tag.")) == "no_tag"
    assert classify_attempt(record("cut off mid", truncated=True)) == "truncated_no_tag"


def test_lowercase_long_algebraic_resolves():
    assert classify_attempt(record("<move>ng1f3</move>")) == ""


def test_san_is_accepted():
    assert classify_attempt(record("<move>Nf3</move>")) == ""


def test_without_a_fen_it_falls_back_to_the_recorded_label():
    """Never invent a re-derivation it cannot support."""
    r = record("<move>Ke7</move>", rejected="illegal: 'Ke7'")
    r["prompt"] = "a prompt with no position in it"
    assert classify_attempt(r) == "illegal"


def test_breakdown_counts_per_side_and_reports_what_changed(tmp_path):
    rows = [
        {"kind": "match_start"},
        record("<move>e2e4</move>", side="white"),
        record("<move>Ke7</move>", side="white", rejected="unparseable: 'Ke7'"),
        record("<move>Ngf6xa8</move>", side="black", rejected="unparseable: 'Ngf6xa8'"),
        record("no tag here", side="black", truncated=True,
               rejected="truncated_no_tag"),
    ]
    path = tmp_path / "m1.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    out = breakdown("m1", directory=tmp_path)
    assert out["white"].accepted == 1
    assert out["white"].illegal == 1
    assert out["white"].relabelled == {"unparseable -> illegal": 1}
    assert out["black"].unparseable == 1
    assert out["black"].truncated_no_tag == 1
    # Nothing changed for black's truncation, so it is not reported as relabelled.
    assert "truncated_no_tag -> truncated_no_tag" not in out["black"].relabelled


def test_a_missing_log_yields_nothing_rather_than_failing(tmp_path):
    """§14 Phase 1 — a report must still build from a PGN alone."""
    assert breakdown("does-not-exist", directory=tmp_path) == {}


def test_a_corrupt_line_does_not_abort_the_rest(tmp_path):
    path = tmp_path / "m2.jsonl"
    path.write_text(
        "{not json\n" + json.dumps(record("<move>e2e4</move>", side="white")) + "\n"
    )
    assert breakdown("m2", directory=tmp_path)["white"].accepted == 1
