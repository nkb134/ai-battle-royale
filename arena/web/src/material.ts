/** Captured pieces and material edge, derived from the FEN on the board. */

const START_COUNTS: Record<string, number> = {
  p: 8, n: 2, b: 2, r: 2, q: 1,
}

const VALUE: Record<string, number> = { p: 1, n: 3, b: 3, r: 5, q: 9 }

const GLYPH: Record<string, string> = {
  p: '♟', n: '♞', b: '♝', r: '♜', q: '♛',
}

interface Material {
  /** Pieces White has captured, i.e. missing black pieces. */
  whiteCaptured: string[]
  blackCaptured: string[]
  /** Positive means White is ahead, in pawns. */
  edge: number
}

export function material(fen: string): Material {
  const placement = fen.split(' ')[0] ?? ''
  const counts: Record<string, number> = {}
  for (const ch of placement) {
    if (/[a-zA-Z]/.test(ch)) counts[ch] = (counts[ch] ?? 0) + 1
  }

  const whiteCaptured: string[] = []
  const blackCaptured: string[] = []
  let whitePoints = 0
  let blackPoints = 0

  for (const [piece, full] of Object.entries(START_COUNTS)) {
    const blackLeft = counts[piece] ?? 0
    const whiteLeft = counts[piece.toUpperCase()] ?? 0
    for (let i = 0; i < full - blackLeft; i++) whiteCaptured.push(GLYPH[piece]!)
    for (let i = 0; i < full - whiteLeft; i++) blackCaptured.push(GLYPH[piece]!)
    whitePoints += whiteLeft * (VALUE[piece] ?? 0)
    blackPoints += blackLeft * (VALUE[piece] ?? 0)
  }

  return { whiteCaptured, blackCaptured, edge: whitePoints - blackPoints }
}
