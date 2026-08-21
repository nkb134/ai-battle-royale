/**
 * The reducer both modes share (§16.2).
 *
 * Live, events arrive over a WebSocket. Recorded, they are read from a replay file.
 * They are the same events, so they fold through the same function. Anything derived
 * from the stream belongs here, not in a component.
 */

import type { ArenaEvent, Classification, Side } from './types'

export interface MoveRow {
  ply: number
  san: string
  uci: string
  fenAfter: string
  elapsedMs: number
  capture: boolean
  check: boolean
  retryCount: number
  panic: boolean
  forcedRandom: boolean
  cpAfter?: number
  cpLoss?: number
  classification?: Classification
}

export interface MatchState {
  matchId: string | null
  white: string
  black: string
  timeControl: string
  fen: string
  lastMove: [string, string] | null
  moves: MoveRow[]
  clockWhite: number | null
  clockBlack: number | null
  /** Whose clock is running, or null between moves and after the end. */
  thinking: Side | null
  tokenBudget: number | null
  cp: number
  lowTime: Record<Side, boolean>
  arrows: string[]
  hanging: string[]
  taunt: { side: Side; text: string } | null
  result: string | null
  termination: string | null
  adjudicated: boolean
  /** Highest seq folded in, so a gap in a live stream is detectable (§7). */
  seq: number
}

export const START_FEN =
  'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

export function initialState(): MatchState {
  return {
    matchId: null,
    white: '',
    black: '',
    timeControl: '',
    fen: START_FEN,
    lastMove: null,
    moves: [],
    clockWhite: null,
    clockBlack: null,
    thinking: null,
    tokenBudget: null,
    cp: 0,
    lowTime: { white: false, black: false },
    arrows: [],
    hanging: [],
    taunt: null,
    result: null,
    termination: null,
    adjudicated: false,
    seq: 0,
  }
}

export function reduce(state: MatchState, event: ArenaEvent): MatchState {
  const next: MatchState = { ...state, seq: Math.max(state.seq, event.seq) }

  switch (event.type) {
    case 'match_start':
      return {
        ...initialState(),
        seq: event.seq,
        matchId: event.match_id,
        white: event.white,
        black: event.black,
        timeControl: event.time_control,
        fen: event.starting_fen,
        clockWhite: event.clock_white ?? null,
        clockBlack: event.clock_black ?? null,
      }

    case 'thinking':
      next.thinking = event.side
      next.tokenBudget = event.token_budget
      next.clockWhite = event.clock_white
      next.clockBlack = event.clock_black
      return next

    case 'move': {
      const row: MoveRow = {
        ply: event.ply,
        san: event.san,
        uci: event.uci,
        fenAfter: event.fen_after,
        elapsedMs: event.elapsed_ms,
        capture: event.capture,
        check: event.check,
        retryCount: event.retry_count,
        panic: event.panic,
        forcedRandom: event.forced_random ?? false,
        cpAfter: event.cp_after,
        cpLoss: event.cp_loss,
        classification: event.classification,
      }
      next.moves = [...state.moves, row]
      next.fen = event.fen_after
      next.lastMove = [event.uci.slice(0, 2), event.uci.slice(2, 4)]
      next.clockWhite = event.clock_white
      next.clockBlack = event.clock_black
      next.thinking = null
      next.arrows = []
      next.hanging = []
      if (typeof event.cp_after === 'number') next.cp = event.cp_after
      return next
    }

    case 'threats':
      // Only paint threats for the position on the board right now. A late-arriving
      // threats event for an older ply is stale and must not draw over the board.
      if (event.ply !== state.moves.at(-1)?.ply) return next
      next.arrows = event.arrows ?? []
      next.hanging = event.hanging ?? []
      return next

    case 'low_time':
      next.lowTime = { ...state.lowTime, [event.side]: true }
      return next

    case 'taunt':
      next.taunt = { side: event.side, text: event.text }
      return next

    case 'match_end':
      next.result = event.result
      next.termination = event.termination
      next.adjudicated = event.adjudicated
      next.thinking = null
      next.arrows = []
      return next

    default:
      return next
  }
}

/** Fold a whole list, for jumping to a position without animating there. */
export function reduceAll(events: ArenaEvent[]): MatchState {
  return events.reduce(reduce, initialState())
}

/** True when the result must not be presented as a clean win (§5.4, §15). */
export function isQualified(termination: string | null, adjudicated: boolean): boolean {
  if (adjudicated) return true
  return termination === 'flag_fall' ||
    termination === 'flag_fall_insufficient_material' ||
    termination === 'illegal_move_forfeit' ||
    termination === 'provider_error'
}

export function formatClock(ms: number | null): string {
  if (ms === null) return '—:—'
  const clamped = Math.max(0, ms)
  const total = Math.floor(clamped / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  if (m >= 10) return `${m}:${String(s).padStart(2, '0')}`
  const tenths = Math.floor((clamped % 1000) / 100)
  return total < 20
    ? `${m}:${String(s).padStart(2, '0')}.${tenths}`
    : `${m}:${String(s).padStart(2, '0')}`
}
