/**
 * Live mode (§16.1). Opt-in, local only.
 *
 * A page served over HTTPS opening a ws://localhost socket is allowed in Chrome and
 * Safari but has historically been blocked by Firefox, so this is a convenience for
 * whoever is running the backend, never something replay mode depends on.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { initialState, reduce, type MatchState } from './matchState'
import type { ArenaEvent } from './types'

export type LiveStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

export function useLiveMatch(url: string | null) {
  const [state, setState] = useState<MatchState>(initialState)
  const [status, setStatus] = useState<LiveStatus>('idle')
  const [gap, setGap] = useState(false)
  const socket = useRef<WebSocket | null>(null)

  const disconnect = useCallback(() => {
    socket.current?.close()
    socket.current = null
    setStatus('idle')
  }, [])

  useEffect(() => {
    if (!url) return
    setStatus('connecting')
    setState(initialState())
    setGap(false)

    const ws = new WebSocket(url)
    socket.current = ws

    ws.onopen = () => setStatus('open')
    ws.onerror = () => setStatus('error')
    ws.onclose = () => setStatus('closed')
    ws.onmessage = (message) => {
      let event: ArenaEvent
      try {
        event = JSON.parse(message.data as string)
      } catch {
        return
      }
      setState((current) => {
        // §7 — a monotonic seq means a gap is detectable rather than silent.
        if (current.seq && event.seq > current.seq + 1) setGap(true)
        return reduce(current, event)
      })
    }

    return () => ws.close()
  }, [url])

  return { state, status, gap, disconnect }
}
