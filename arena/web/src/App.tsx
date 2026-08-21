import { useCallback, useEffect, useState } from 'react'
import { MatchScreen } from './components/MatchScreen'
import { ReportScreen } from './components/ReportScreen'
import { SetupScreen } from './components/SetupScreen'
import { usePlayback } from './usePlayback'
import { useLiveMatch } from './useLiveMatch'
import type { Replay, ReplayIndexEntry, Report } from './types'

const BASE = import.meta.env.BASE_URL

/** Starting clock in ms, parsed from a "15+10" label, for the low-time thresholds. */
function initialMsFor(timeControl: string): number | null {
  const match = /^(\d+)\+(\d+)$/.exec(timeControl.trim())
  if (!match) return null
  return Number(match[1]) * 60_000
}

const SPEEDS = [1, 2, 4, 8, 16]

export default function App() {
  const [entries, setEntries] = useState<ReplayIndexEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [replay, setReplay] = useState<Replay | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [liveUrl, setLiveUrl] = useState<string | null>(null)
  const [showArrows, setShowArrows] = useState(true)

  const playback = usePlayback(replay?.events ?? null)
  const live = useLiveMatch(liveUrl)

  useEffect(() => {
    fetch(`${BASE}replays/index.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`index.json: ${r.status}`)
        return r.json()
      })
      .then((data) => setEntries(data.matches ?? []))
      .catch((e) => setError(String(e.message ?? e)))
      .finally(() => setLoading(false))
  }, [])

  const openMatch = useCallback((matchId: string) => {
    setError(null)
    fetch(`${BASE}replays/${matchId}.json`)
      .then((r) => {
        if (!r.ok) throw new Error(`${matchId}: ${r.status}`)
        return r.json()
      })
      .then((data: Replay) => setReplay(data))
      .catch((e) => setError(String(e.message ?? e)))
  }, [])

  // A report is optional: it only exists once `make analyze` has been run and the
  // result committed, so a missing one is not an error.
  const openReport = useCallback((matchId: string) => {
    fetch(`${BASE}reports/${matchId}.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Report | null) => data && setReport(data))
      .catch(() => undefined)
  }, [])

  const back = useCallback(() => {
    setReplay(null)
    setReport(null)
    setLiveUrl(null)
    live.disconnect()
  }, [live])

  // Live mode wins when connected; otherwise the replay drives the board.
  if (liveUrl) {
    return (
      <MatchScreen
        state={live.state}
        initialMs={initialMsFor(live.state.timeControl)}
        showArrows={showArrows}
        onToggleArrows={() => setShowArrows((v) => !v)}
        onBack={back}
        banner={
          <div className={`banner ${live.status === 'open' ? 'live' : 'warn'}`}>
            <span className="dot" />
            {live.status === 'open'
              ? 'Live from your local backend'
              : `Live connection ${live.status}`}
            {live.gap && <em> · missed events, the stream has a gap</em>}
          </div>
        }
      />
    )
  }

  if (report) {
    return <ReportScreen report={report} onBack={back} />
  }

  if (replay) {
    return (
      <MatchScreen
        state={playback.state}
        initialMs={initialMsFor(replay.time_control)}
        showArrows={showArrows}
        onToggleArrows={() => setShowArrows((v) => !v)}
        onBack={back}
        banner={
          <div className="banner replay">
            Recording · played back at the real timings, {playback.speed}× faster
          </div>
        }
        controls={
          <div className="controls">
            <button onClick={playback.stepBack} disabled={playback.index === 0}>
              ◀
            </button>
            <button className="primary" onClick={playback.toggle}>
              {playback.playing ? 'Pause' : 'Play'}
            </button>
            <button
              onClick={playback.stepForward}
              disabled={playback.index >= playback.total}
            >
              ▶
            </button>
            <input
              type="range"
              min={0}
              max={playback.total}
              value={playback.index}
              onChange={(e) => playback.seek(Number(e.target.value))}
            />
            <select
              value={playback.speed}
              onChange={(e) => playback.setSpeed(Number(e.target.value))}
            >
              {SPEEDS.map((s) => (
                <option key={s} value={s}>{s}×</option>
              ))}
            </select>
          </div>
        }
      />
    )
  }

  return (
    <SetupScreen
      entries={entries}
      loading={loading}
      error={error}
      onOpen={openMatch}
      onOpenReport={openReport}
      onConnectLive={setLiveUrl}
    />
  )
}
