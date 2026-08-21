/**
 * Replay playback (§16.2).
 *
 * The recorded stream is played at the timings it actually happened at: each move's
 * `elapsed_ms` is how long that model really took, so the gap before a move is that
 * move's own elapsed time. Nothing is re-timed or invented. `speed` scales the whole
 * playback for the viewer's patience, and is shown in the UI so it is never mistaken
 * for the real pace.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { initialState, reduce, type MatchState } from './matchState'
import type { ArenaEvent } from './types'

/** Wall-clock delay before each event, derived from the recording. */
function delaysFor(events: ArenaEvent[]): number[] {
  return events.map((event) => {
    if (event.type === 'move') return Math.max(120, event.elapsed_ms)
    // Everything else is bookkeeping that happened effectively instantly.
    return event.type === 'match_start' ? 600 : 0
  })
}

export interface Playback {
  state: MatchState
  index: number
  total: number
  playing: boolean
  speed: number
  play: () => void
  pause: () => void
  toggle: () => void
  setSpeed: (s: number) => void
  seek: (index: number) => void
  stepBack: () => void
  stepForward: () => void
}

export function usePlayback(events: ArenaEvent[] | null): Playback {
  const list = useMemo(() => events ?? [], [events])
  const delays = useMemo(() => delaysFor(list), [list])

  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(4)
  const [state, setState] = useState<MatchState>(initialState)

  const timer = useRef<number | null>(null)

  // Rebuild state from scratch on a seek. Folding from the start is cheap and keeps
  // one code path, rather than a forward reducer plus an inverse one.
  useEffect(() => {
    let s = initialState()
    for (let i = 0; i < index; i++) {
      const event = list[i]
      if (event) s = reduce(s, event)
    }
    setState(s)
  }, [index, list])

  useEffect(() => {
    if (!playing || index >= list.length) return
    const delay = (delays[index] ?? 0) / speed
    timer.current = window.setTimeout(() => setIndex((i) => i + 1), delay)
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current)
    }
  }, [playing, index, list.length, delays, speed])

  useEffect(() => {
    if (index >= list.length && list.length > 0) setPlaying(false)
  }, [index, list.length])

  useEffect(() => {
    // Fold match_start straight away. The names, clocks and time control belong to the
    // match, not to its first move, and a viewer should see them before pressing play.
    setIndex(list[0]?.type === 'match_start' ? 1 : 0)
    setPlaying(false)
  }, [list])

  const seek = useCallback(
    (target: number) => {
      const floor = list[0]?.type === 'match_start' ? 1 : 0
      setIndex(Math.max(floor, Math.min(list.length, target)))
    },
    [list],
  )

  /** Step by move, not by event: the viewer thinks in moves. */
  const stepBy = useCallback(
    (direction: -1 | 1) => {
      setPlaying(false)
      setIndex((current) => {
        const floor = list[0]?.type === 'match_start' ? 1 : 0
        let i = current + direction
        while (i > floor && i < list.length && list[i]?.type !== 'move') i += direction
        return Math.max(floor, Math.min(list.length, direction === 1 ? i + 1 : i))
      })
    },
    [list],
  )

  return {
    state,
    index,
    total: list.length,
    playing,
    speed,
    play: () => setPlaying(true),
    pause: () => setPlaying(false),
    toggle: () => setPlaying((p) => !p),
    setSpeed,
    seek,
    stepBack: () => stepBy(-1),
    stepForward: () => stepBy(1),
  }
}
