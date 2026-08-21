/**
 * The post-match report (§8.4).
 *
 * ACPL in panic versus the rest of the game leads, because it is the payoff of the
 * whole clock system and §8.4 asks for it prominently. Everything else is supporting
 * evidence.
 */

import { Board } from './Board'
import { EvalGraph } from './EvalGraph'
import { isQualified } from '../matchState'
import type { Report, SideStats } from '../types'

interface Props {
  report: Report
  onBack: () => void
}

function fmt(n: number | null, suffix = ''): string {
  return n === null ? '—' : `${n}${suffix}`
}

function PanicPanel({ name, stats }: { name: string; stats: SideStats }) {
  const penalty =
    stats.acpl_panic !== null && stats.acpl_calm !== null
      ? Math.round((stats.acpl_panic - stats.acpl_calm) * 10) / 10
      : null

  return (
    <div className="panic-panel">
      <h3>{name}</h3>
      {stats.panic_plies === 0 ? (
        <p className="muted">Never dropped below 20% of the clock.</p>
      ) : (
        <>
          <div className="panic-figures">
            <div>
              <span className="figure">{fmt(stats.acpl_panic)}</span>
              <span className="figure-label">ACPL in panic</span>
            </div>
            <div>
              <span className="figure">{fmt(stats.acpl_calm)}</span>
              <span className="figure-label">ACPL otherwise</span>
            </div>
            <div>
              <span className={`figure ${penalty !== null && penalty > 0 ? 'worse' : 'better'}`}>
                {penalty !== null && penalty > 0 ? '+' : ''}{fmt(penalty)}
              </span>
              <span className="figure-label">difference</span>
            </div>
          </div>
          <p className="muted">
            {stats.panic_plies} of {stats.moves} moves were played under a hard token
            cap with a shrinking clock.
          </p>
        </>
      )}
    </div>
  )
}

function StatsTable({ white, black, whiteName, blackName }: {
  white: SideStats; black: SideStats; whiteName: string; blackName: string
}) {
  const rows: [string, (s: SideStats) => string][] = [
    ['Moves', (s) => String(s.moves)],
    ['ACPL', (s) => fmt(s.acpl)],
    ['Blunders', (s) => String(s.blunders)],
    ['Mistakes', (s) => String(s.mistakes)],
    ['Brilliant', (s) => String(s.brilliant)],
    ['Illegal attempts', (s) => String(s.illegal_moves)],
    ['Random moves forced', (s) => String(s.forced_random)],
    ['Mean reasoning tokens', (s) => fmt(s.mean_reasoning_tokens)],
    ['Mean token budget', (s) => fmt(s.mean_token_budget)],
    ['Moves over budget', (s) => String(s.budget_overrun_plies)],
  ]

  return (
    <table className="stats">
      <thead>
        <tr><th /><th>{whiteName}</th><th>{blackName}</th></tr>
      </thead>
      <tbody>
        {rows.map(([label, get]) => (
          <tr key={label}>
            <th>{label}</th>
            <td>{get(white)}</td>
            <td>{get(black)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function ReportScreen({ report, onBack }: Props) {
  const qualified = isQualified(report.termination, report.adjudicated)

  return (
    <div className="report">
      <header className="match-header">
        <button className="link" onClick={onBack}>← All matches</button>
        <span className="match-title">
          {report.white} <span className="vs">vs</span> {report.black}
          <span className="tc">{report.time_control}</span>
        </span>
      </header>

      <div className={`result ${qualified ? 'qualified' : ''}`}>
        <strong>{report.result}</strong>
        <span>{report.termination.replace(/_/g, ' ')}</span>
        {qualified && <em>not a clean finish</em>}
      </div>

      {report.opening_name && (
        <p className="muted opening">
          {report.opening_eco} · {report.opening_name}
          {report.left_book_at_ply && <> · left book at ply {report.left_book_at_ply}</>}
        </p>
      )}

      {/* §8.4 — the payoff of the clock system gets top billing. */}
      <section className="section">
        <h2>Under time pressure</h2>
        <div className="panic-grid">
          <PanicPanel name={report.white} stats={report.white_stats} />
          <PanicPanel name={report.black} stats={report.black_stats} />
        </div>
      </section>

      <section className="section">
        <h2>Evaluation</h2>
        <EvalGraph evals={report.eval_graph} moments={report.key_moments} />
      </section>

      <section className="section">
        <h2>Key moments</h2>
        {report.key_moments.length === 0 ? (
          <p className="muted">Nothing swung the evaluation.</p>
        ) : (
          <div className="moments">
            {report.key_moments.map((m) => (
              <figure className="moment" key={m.ply}>
                <div className="moment-board">
                  <Board
                    fen={m.fen_before}
                    lastMove={null}
                    arrows={m.engine_line ? [m.engine_line] : []}
                    hanging={[]}
                    showArrows
                    orientation={m.side}
                  />
                </div>
                <figcaption>
                  <span className="moment-head">
                    Ply {m.ply} · <strong>{m.san}</strong>
                    <span className={`chip ${m.classification}`}>{m.classification}</span>
                    {m.panic && <span className="chip panic">panic</span>}
                  </span>
                  <p>{m.sentence}</p>
                  <p className="muted">
                    {(m.cp_before / 100).toFixed(2)} → {(m.cp_after / 100).toFixed(2)}
                    {m.engine_line && <> · engine wanted {m.engine_line}</>}
                  </p>
                </figcaption>
              </figure>
            ))}
          </div>
        )}
      </section>

      <section className="section">
        <h2>By the numbers</h2>
        <StatsTable
          white={report.white_stats}
          black={report.black_stats}
          whiteName={report.white}
          blackName={report.black}
        />
      </section>
    </div>
  )
}
