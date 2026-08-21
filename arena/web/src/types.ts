/**
 * The §7 event protocol. Live over WebSocket and recorded in a replay file are the
 * same events in the same order, so this file is the single definition of both.
 */

export type Side = 'white' | 'black'

export interface BaseEvent {
  seq: number
  type: string
}

export interface MatchStartEvent extends BaseEvent {
  type: 'match_start'
  match_id: string
  white: string
  black: string
  time_control: string
  starting_fen: string
  clock_white: number | null
  clock_black: number | null
  increment_ms: number
}

export interface ThinkingEvent extends BaseEvent {
  type: 'thinking'
  side: Side
  token_budget: number
  clock_white: number | null
  clock_black: number | null
}

export type Classification =
  | 'best' | 'good' | 'inaccuracy' | 'mistake' | 'blunder' | 'brilliant'

export interface MoveEvent extends BaseEvent {
  type: 'move'
  ply: number
  san: string
  uci: string
  fen_after: string
  clock_white: number | null
  clock_black: number | null
  elapsed_ms: number
  capture: boolean
  check: boolean
  retry_count: number
  panic: boolean
  forced_random?: boolean
  /** Attached by analysis, which trails the move (§7). May be absent. */
  cp_after?: number
  cp_loss?: number
  classification?: Classification
}

export interface ThreatsEvent extends BaseEvent {
  type: 'threats'
  ply: number
  best_reply_uci: string | null
  hanging: string[]
  arrows: string[]
}

export interface TauntEvent extends BaseEvent {
  type: 'taunt'
  side: Side
  text: string
  trigger: string
}

export interface LowTimeEvent extends BaseEvent {
  type: 'low_time'
  side: Side
  remaining_ms: number
}

export interface MatchEndEvent extends BaseEvent {
  type: 'match_end'
  result: string
  termination: string
  adjudicated: boolean
  report_url?: string
}

export type ArenaEvent =
  | MatchStartEvent | ThinkingEvent | MoveEvent | ThreatsEvent
  | TauntEvent | LowTimeEvent | MatchEndEvent

/** A recorded match: the header, plus exactly the event list (§16.2). */
export interface Replay {
  format_version: number
  match_id: string
  white: string
  black: string
  white_model: string
  black_model: string
  time_control: string
  config_hash: string
  started_at: string
  ended_at: string
  result: string
  termination: string
  adjudicated: boolean
  ply_count: number
  events: ArenaEvent[]
}

export interface ReplayIndexEntry {
  match_id: string
  white: string
  black: string
  time_control: string
  result: string
  termination: string
  adjudicated: boolean
  ply_count: number
  started_at: string
}
