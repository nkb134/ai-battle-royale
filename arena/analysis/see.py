"""Static exchange evaluation. §8.2, §8.3.

python-chess has no SEE, so this is the swap-off algorithm: play out the capture
sequence on one square, each side always recapturing with its least valuable attacker,
and let either side stand pat when continuing would lose material.

Used for two things: flagging a sacrifice as `brilliant` (§8.2) and finding hanging
pieces for the threat layer (§8.3).
"""

from __future__ import annotations

import chess

VALUES: dict[int, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20_000,
}


def piece_value(piece_type: int | None) -> int:
    return VALUES.get(piece_type, 0) if piece_type else 0


def _least_valuable_attacker(
    board: chess.Board, square: int, color: bool, occupied: int
) -> int | None:
    """The cheapest piece of `color` still on `occupied` that attacks `square`.

    `attackers_mask` intersects with the board's real colour sets, so squares already
    consumed by the exchange are masked out here.
    """
    attackers = board.attackers_mask(color, square, occupied) & occupied
    if not attackers:
        return None
    best_sq, best_val = None, None
    for sq in chess.scan_forward(attackers):
        val = piece_value(board.piece_type_at(sq))
        if best_val is None or val < best_val:
            best_sq, best_val = sq, val
    return best_sq


def see(board: chess.Board, move: chess.Move) -> int:
    """Centipawn outcome of the exchange on `move.to_square`, from the mover's view.

    Negative means the mover comes out down material if the opponent plays the
    exchange out correctly. A quiet move onto a safe square is 0.
    """
    target = move.to_square

    if board.is_en_passant(move):
        captured_value = VALUES[chess.PAWN]
    else:
        captured_value = piece_value(board.piece_type_at(target))

    attacker_type = board.piece_type_at(move.from_square)
    if attacker_type is None:
        return 0

    occupied = board.occupied & ~chess.BB_SQUARES[move.from_square]
    if board.is_en_passant(move) and board.ep_square is not None:
        captured_square = board.ep_square + (-8 if board.turn == chess.WHITE else 8)
        occupied &= ~chess.BB_SQUARES[captured_square]

    gains = [captured_value]
    side = not board.turn
    depth = 0

    while True:
        depth += 1
        # Speculative: what this side nets if it does recapture here.
        gains.append(piece_value(attacker_type) - gains[depth - 1])
        if max(-gains[depth - 1], gains[depth]) < 0:
            break  # both sides would rather stand pat

        from_sq = _least_valuable_attacker(board, target, side, occupied)
        if from_sq is None:
            break

        next_type = board.piece_type_at(from_sq)
        if next_type == chess.KING:
            # A king may only recapture onto a square nobody still defends.
            remaining = occupied & ~chess.BB_SQUARES[from_sq]
            if board.attackers_mask(not side, target, remaining) & remaining:
                break

        attacker_type = next_type
        occupied &= ~chess.BB_SQUARES[from_sq]
        side = not side

    # Fold back. The final speculative entry is dropped: the loop broke because that
    # capture never happens. Each earlier step may stand pat instead of recapturing.
    depth = len(gains) - 1
    while depth > 1:
        depth -= 1
        gains[depth - 1] = -max(-gains[depth - 1], gains[depth])
    return gains[0]


def hanging_squares(board: chess.Board, color: bool) -> list[str]:
    """Squares where `color` has a piece that can be won by static exchange (§8.3)."""
    out = []
    for square in chess.scan_forward(board.occupied_co[color]):
        piece = board.piece_at(square)
        if piece is None or piece.piece_type == chess.KING:
            continue
        probe = board.copy(stack=False)
        probe.turn = not color
        best = 0
        for move in probe.legal_moves:
            if move.to_square != square:
                continue
            best = max(best, see(probe, move))
        if best > 0:
            out.append(chess.square_name(square))
    return out
