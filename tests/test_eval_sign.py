"""§8.1 sign convention. The Phase 0 gate: this passes before anything else reads an eval.

Every stored eval is centipawns from White's point of view, whoever is to move.
"""

import chess
import pytest

from arena.analysis.stockfish import (
    MATE_SCORE,
    AnalysisConfig,
    EnginePool,
    clamp_mate,
    cp_from_white,
    cp_loss,
)

FAST = AnalysisConfig(depth=10, movetime_ms=150)

# Startpos with one queen removed, so the only asymmetry is the material. Each is tested
# with either side to move: the stored sign must track the material, never the mover.
WHITE_UP_W_TO_MOVE = "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
WHITE_UP_B_TO_MOVE = "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1"
BLACK_UP_W_TO_MOVE = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"
BLACK_UP_B_TO_MOVE = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR b KQkq - 0 1"


def test_pov_conversion_is_white_relative():
    """A PovScore is relative to the side to move; .white() is what makes it absolute."""
    from chess.engine import Cp, PovScore

    # +300 for Black, with Black to move, is -300 from White's point of view.
    assert cp_from_white(PovScore(Cp(300), chess.BLACK)) == -300
    # +300 for White, with White to move, stays +300.
    assert cp_from_white(PovScore(Cp(300), chess.WHITE)) == 300


def test_mate_clamps_both_directions():
    assert clamp_mate(99_999) == MATE_SCORE
    assert clamp_mate(-99_999) == -MATE_SCORE
    assert clamp_mate(250) == 250


@pytest.mark.parametrize("fen", [WHITE_UP_W_TO_MOVE, WHITE_UP_B_TO_MOVE])
async def test_white_material_advantage_is_positive_regardless_of_side_to_move(fen):
    async with EnginePool(size=1, cfg=FAST) as pool:
        ev = await pool.evaluate(chess.Board(fen))
    assert ev.cp > 0, f"{fen} evaluated {ev.cp}, expected positive for White"


@pytest.mark.parametrize("fen", [BLACK_UP_W_TO_MOVE, BLACK_UP_B_TO_MOVE])
async def test_black_material_advantage_is_negative_regardless_of_side_to_move(fen):
    async with EnginePool(size=1, cfg=FAST) as pool:
        ev = await pool.evaluate(chess.Board(fen))
    assert ev.cp < 0, f"{fen} evaluated {ev.cp}, expected negative for White"


async def test_startpos_is_roughly_balanced():
    async with EnginePool(size=1, cfg=FAST) as pool:
        ev = await pool.evaluate(chess.Board())
    assert abs(ev.cp) < 150


async def test_checkmate_delivered_by_white_is_plus_mate():
    board = chess.Board("rnbqkbnr/ppppp2p/5p2/6pQ/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 1 3")
    assert board.is_checkmate()
    async with EnginePool(size=1, cfg=FAST) as pool:
        ev = await pool.evaluate(board)
    assert ev.cp == MATE_SCORE


async def test_checkmate_delivered_by_black_is_minus_mate():
    board = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
    assert board.is_checkmate()
    async with EnginePool(size=1, cfg=FAST) as pool:
        ev = await pool.evaluate(board)
    assert ev.cp == -MATE_SCORE


async def test_stalemate_is_zero_not_a_mate():
    board = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert board.is_stalemate()
    async with EnginePool(size=1, cfg=FAST) as pool:
        ev = await pool.evaluate(board)
    assert ev.cp == 0


def test_cp_loss_is_from_the_movers_point_of_view():
    """§8.2 — the swing against the mover, never negative."""
    # White was +100, is now -50: White dropped 150.
    assert cp_loss(100, -50, mover_is_white=True) == 150
    # Black was at -100 (White's POV), now +50: Black dropped 150.
    assert cp_loss(-100, 50, mover_is_white=False) == 150
    # Improving on the engine's best is impossible; it floors at zero.
    assert cp_loss(100, 300, mover_is_white=True) == 0
    assert cp_loss(-100, -300, mover_is_white=False) == 0


def test_cp_loss_symmetry_holds_for_the_same_swing():
    assert cp_loss(0, -200, mover_is_white=True) == cp_loss(0, 200, mover_is_white=False)


async def test_engine_pool_closes_every_process():
    pool = EnginePool(size=2, cfg=FAST)
    await pool.open()
    await pool.evaluate(chess.Board())
    await pool.close()
    await pool.close()  # idempotent
    assert pool._engines == []


def test_cp_loss_is_capped_so_mate_scores_do_not_swamp_acpl():
    """A mate score is +/-10000. Averaged raw, one lost position makes ACPL
    meaningless — a random-mover match produced an ACPL of 6853. Evaluations are
    clamped before the difference is taken, so a hopeless position contributes a
    large-but-bounded number instead of a mate score."""
    from arena.analysis.stockfish import ACPL_CAP

    # White goes from winning to mated: bounded, not 20000.
    assert cp_loss(MATE_SCORE, -MATE_SCORE, mover_is_white=True) == 2 * ACPL_CAP
    # Ordinary losses are untouched by the cap.
    assert cp_loss(100, -50, mover_is_white=True) == 150


def test_the_cap_does_not_change_which_band_a_move_lands_in():
    """§8.2 bands top out at 300, well inside the cap."""
    from arena.analysis.annotate import classify

    assert classify(cp_loss(0, -400, mover_is_white=True)) == "blunder"
    assert classify(cp_loss(0, -100, mover_is_white=True)) == "inaccuracy"


def test_already_lost_positions_do_not_keep_accruing_loss():
    """Once both sides are past the cap the move cannot be blamed for a further drop."""
    assert cp_loss(-5000, -9000, mover_is_white=True) == 0
