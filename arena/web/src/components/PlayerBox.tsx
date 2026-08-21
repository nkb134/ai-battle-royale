/**
 * A player box: face placeholder, name, clock, captured pieces (§12).
 *
 * The face is a placeholder square until Phase 4. The clock turns amber under 20% and
 * red under 10% of the starting clock.
 */

import { formatClock } from '../matchState'
import type { Side } from '../types'

interface Props {
  side: Side
  name: string
  clockMs: number | null
  initialMs: number | null
  active: boolean
  thinking: boolean
  tokenBudget: number | null
  captured: string[]
  materialEdge: number
  taunt: string | null
}

function clockClass(clockMs: number | null, initialMs: number | null): string {
  if (clockMs === null || initialMs === null || initialMs === 0) return ''
  const fraction = clockMs / initialMs
  if (fraction < 0.1) return 'critical'
  if (fraction < 0.2) return 'low'
  return ''
}

export function PlayerBox({
  side, name, clockMs, initialMs, active, thinking, tokenBudget,
  captured, materialEdge, taunt,
}: Props) {
  return (
    <div className={`playerbox ${active ? 'active' : ''}`}>
      <div className={`face face-${side} ${thinking ? 'face-thinking' : ''}`}>
        <span className="face-placeholder">{side === 'white' ? '□' : '■'}</span>
      </div>

      <div className="playerbox-main">
        <div className="playerbox-name">
          {name || '—'}
          {thinking && tokenBudget !== null && (
            <span className="budget" title="Token budget for this move (§6.3)">
              {tokenBudget} tok
            </span>
          )}
        </div>
        <div className="captured">
          {captured.join('')}
          {materialEdge > 0 && <span className="edge">+{materialEdge}</span>}
        </div>
      </div>

      {taunt && <div className="taunt">{taunt}</div>}

      <div className={`clock ${clockClass(clockMs, initialMs)} ${thinking ? 'running' : ''}`}>
        {formatClock(clockMs)}
      </div>
    </div>
  )
}
