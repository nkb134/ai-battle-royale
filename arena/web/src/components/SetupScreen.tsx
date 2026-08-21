/**
 * The landing screen.
 *
 * On Pages this is the archive: every recorded match, with its result and how it
 * ended. Flagged and adjudicated results are labelled here, not just in the report,
 * because this list is where most people form an impression of them (§5.4, §15).
 *
 * Live mode is offered alongside, and is only useful to whoever is running the
 * backend locally (§16.1).
 */

import { useState } from 'react'
import type { ReplayIndexEntry } from '../types'

interface Props {
  entries: ReplayIndexEntry[]
  loading: boolean
  error: string | null
  onOpen: (matchId: string) => void
  onOpenReport: (matchId: string) => void
  onConnectLive: (url: string) => void
}

const DEFAULT_LIVE_URL = 'ws://localhost:8000/ws'

function resultLabel(entry: ReplayIndexEntry): string {
  const winner =
    entry.result === '1-0' ? entry.white
      : entry.result === '0-1' ? entry.black
        : null
  if (entry.result === '*') return 'abandoned'
  if (!winner) return 'draw'
  return `${winner} won`
}

function qualifier(entry: ReplayIndexEntry): string | null {
  if (entry.adjudicated) return 'adjudicated'
  if (entry.termination.startsWith('flag_fall')) return 'on time'
  if (entry.termination === 'illegal_move_forfeit') return 'forfeit'
  if (entry.termination === 'provider_error') return 'provider error'
  return null
}

export function SetupScreen({
  entries, loading, error, onOpen, onOpenReport, onConnectLive,
}: Props) {
  const [liveUrl, setLiveUrl] = useState(DEFAULT_LIVE_URL)
  const [showLive, setShowLive] = useState(false)

  return (
    <div className="setup">
      <header className="setup-header">
        <h1>Arena</h1>
        <p className="tagline">
          Two language models, one chess clock that actually runs.
        </p>
      </header>

      <section className="setup-explainer">
        <p>
          Models are told how much time they have left and are capped at a token
          budget computed from it, because the only way a model can play faster is to
          reason less. Illegal moves are retried, and the retries come off the clock.
        </p>
        <p className="muted">
          These are recordings, played back at the timings they really happened at.
          The engine runs locally — this page is a static archive, not a live server.
        </p>
      </section>

      <section className="archive">
        <h2>Recorded matches</h2>
        {loading && <p className="muted">Loading…</p>}
        {error && <p className="error">{error}</p>}
        {!loading && !error && entries.length === 0 && (
          <p className="muted">
            No matches recorded yet. Run <code>make match</code> and commit the replay.
          </p>
        )}
        <ul className="archive-list">
          {entries.map((entry) => (
            <li key={entry.match_id} className="archive-item">
              <button className="archive-row" onClick={() => onOpen(entry.match_id)}>
                <span className="archive-players">
                  {entry.white} <span className="vs">vs</span> {entry.black}
                </span>
                <span className="archive-tc">{entry.time_control}</span>
                <span className="archive-result">
                  {resultLabel(entry)}
                  {qualifier(entry) && (
                    <em className="qualifier"> · {qualifier(entry)}</em>
                  )}
                </span>
                <span className="archive-plies">
                  {entry.ply_count} plies
                  {/* The clock only tells you something when it actually bit. */}
                  {entry.panic_plies ? (
                    <em className="panic-flag" title="Plies played under panic mode">
                      {" "}· {entry.panic_plies} in panic
                    </em>
                  ) : null}
                </span>
              </button>
              {entry.has_report !== false && (
                <button
                  className="archive-report link"
                  onClick={() => onOpenReport(entry.match_id)}
                  title="Post-match report"
                >
                  report
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section className="live">
        <button className="link" onClick={() => setShowLive((v) => !v)}>
          {showLive ? '−' : '+'} Watch a live match from a local backend
        </button>
        {showLive && (
          <div className="live-form">
            <p className="muted">
              Only works while <code>make serve</code> is running on your own machine.
              Firefox blocks this from an HTTPS page; Chrome and Safari allow it.
            </p>
            <input
              value={liveUrl}
              onChange={(e) => setLiveUrl(e.target.value)}
              spellCheck={false}
            />
            <button onClick={() => onConnectLive(liveUrl)}>Connect</button>
          </div>
        )}
      </section>
    </div>
  )
}
