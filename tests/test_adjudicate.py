"""§5.4, §6.1."""

import chess

from arena.engine.adjudicate import (
    AdjudicationConfig,
    Adjudicator,
    flag_fall_outcome,
    natural_outcome,
)

CFG = AdjudicationConfig()


def test_checkmate_is_detected_and_is_clean():
    board = chess.Board("rnbqkbnr/ppppp2p/5p2/6pQ/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 1 3")
    out = natural_outcome(board)
    assert out.result == "1-0" and out.termination == "checkmate"
    assert out.is_clean and not out.adjudicated


def test_stalemate_is_a_draw():
    out = natural_outcome(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"))
    assert out.result == "1/2-1/2" and out.termination == "stalemate"


def test_ongoing_position_has_no_natural_outcome():
    assert natural_outcome(chess.Board()) is None


def test_flag_fall_loses_and_is_never_clean():
    """§15 — a flagged result must not be presentable as a clean win."""
    out = flag_fall_outcome("white", chess.Board())
    assert out.result == "0-1" and out.termination == "flag_fall"
    assert not out.is_clean


def test_flag_fall_is_a_draw_when_the_opponent_cannot_mate():
    """§6.1 — lone king cannot mate, so the flag is a draw."""
    board = chess.Board("8/8/8/4k3/8/8/4K3/8 w - - 0 1")
    assert flag_fall_outcome("white", board).result == "1/2-1/2"


def test_flag_fall_stands_when_the_opponent_has_a_rook():
    board = chess.Board("8/8/8/4k3/8/8/4K3/7r w - - 0 1")
    assert flag_fall_outcome("white", board).result == "0-1"


def test_resignation_needs_six_consecutive_plies():
    adj = Adjudicator(CFG)
    out = None
    for ply in range(1, 6):
        out = adj.observe(
            ply=ply, cp_after=-1200, side_to_move="white",
            was_capture=False, was_pawn_move=True,
        )
        assert out is None
    out = adj.observe(
        ply=6, cp_after=-1200, side_to_move="white",
        was_capture=False, was_pawn_move=True,
    )
    assert out.result == "0-1"
    assert out.termination == "adjudicated_resignation"
    assert out.adjudicated and not out.is_clean


def test_a_single_recovery_resets_the_resignation_streak():
    adj = Adjudicator(CFG)
    for ply in range(1, 5):
        adj.observe(ply=ply, cp_after=-1200, side_to_move="white",
                    was_capture=False, was_pawn_move=True)
    adj.observe(ply=5, cp_after=-100, side_to_move="white",
                was_capture=False, was_pawn_move=True)
    for ply in range(6, 11):
        assert adj.observe(ply=ply, cp_after=-1200, side_to_move="white",
                           was_capture=False, was_pawn_move=True) is None


def test_resignation_is_relative_to_the_side_to_move():
    """+1200 for White means Black is the one lost, not White."""
    adj = Adjudicator(CFG)
    out = None
    for ply in range(1, 7):
        out = adj.observe(ply=ply, cp_after=1200, side_to_move="black",
                          was_capture=False, was_pawn_move=True)
    assert out.result == "1-0"


def test_quiet_level_draw_after_thirty_plies():
    adj = Adjudicator(CFG)
    out = None
    for ply in range(1, 31):
        out = adj.observe(ply=ply, cp_after=10, side_to_move="white",
                          was_capture=False, was_pawn_move=False)
    assert out.result == "1/2-1/2" and out.termination == "adjudicated_draw"


def test_a_capture_resets_the_draw_streak():
    adj = Adjudicator(CFG)
    for ply in range(1, 29):
        adj.observe(ply=ply, cp_after=10, side_to_move="white",
                    was_capture=False, was_pawn_move=False)
    adj.observe(ply=29, cp_after=10, side_to_move="white",
                was_capture=True, was_pawn_move=False)
    assert adj.observe(ply=30, cp_after=10, side_to_move="white",
                       was_capture=False, was_pawn_move=False) is None


def test_ply_cap_ends_the_game():
    adj = Adjudicator(AdjudicationConfig(max_plies=4))
    for ply in range(1, 4):
        adj.observe(ply=ply, cp_after=0, side_to_move="white",
                    was_capture=True, was_pawn_move=False)
    out = adj.observe(ply=4, cp_after=0, side_to_move="white",
                      was_capture=True, was_pawn_move=False)
    assert out.termination == "adjudicated_ply_cap" and out.adjudicated
