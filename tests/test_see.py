"""§8.2, §8.3 — static exchange evaluation."""

import chess

from arena.analysis.see import VALUES, hanging_squares, see


def test_free_pawn_capture_wins_a_pawn():
    board = chess.Board("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
    assert see(board, chess.Move.from_uci("e4d5")) == VALUES[chess.PAWN]


def test_defended_pawn_capture_is_an_even_trade():
    """Pawn takes pawn, pawn recaptures: even."""
    board = chess.Board("4k3/8/2p5/3p4/4P3/8/8/4K3 w - - 0 1")
    assert see(board, chess.Move.from_uci("e4d5")) == 0


def test_queen_takes_defended_pawn_loses_material():
    board = chess.Board("4k3/8/2p5/3p4/8/8/3Q4/4K3 w - - 0 1")
    assert see(board, chess.Move.from_uci("d2d5")) < 0


def test_quiet_move_to_a_safe_square_is_zero():
    board = chess.Board()
    assert see(board, chess.Move.from_uci("e2e4")) == 0


def test_moving_a_knight_where_a_pawn_can_take_it_is_negative():
    board = chess.Board("4k3/8/8/2p5/8/3N4/8/4K3 w - - 0 1")
    assert see(board, chess.Move.from_uci("d3b4")) < 0


def test_xray_defender_is_counted():
    """A rook behind a rook keeps defending the square once the first one is used."""
    board = chess.Board("4k3/8/8/8/8/4p3/4R3/4R1K1 w - - 0 1")
    # Rxe3, pawn is free, and the second rook backs up the first.
    assert see(board, chess.Move.from_uci("e2e3")) == VALUES[chess.PAWN]


def test_en_passant_capture_wins_a_pawn():
    board = chess.Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2")
    move = chess.Move.from_uci("e5d6")
    assert board.is_en_passant(move)
    assert see(board, move) == VALUES[chess.PAWN]


def test_hanging_squares_finds_an_undefended_piece():
    board = chess.Board("4k3/8/8/3n4/8/8/3R4/4K3 w - - 0 1")
    assert "d5" in hanging_squares(board, chess.BLACK)


def test_defended_piece_is_not_hanging():
    board = chess.Board("4k3/8/2p5/3n4/8/8/3R4/4K3 w - - 0 1")
    # Rxd5 cxd5 loses the rook for a knight, so d5 is not hanging.
    assert "d5" not in hanging_squares(board, chess.BLACK)


def test_startpos_has_nothing_hanging():
    assert hanging_squares(chess.Board(), chess.WHITE) == []
    assert hanging_squares(chess.Board(), chess.BLACK) == []
