/**
 * The eval graph (§8.4). White's point of view throughout, like every other eval in
 * the project (§8.1). Turning points are marked, not just drawn.
 */

import type { KeyMoment } from '../types'

const W = 640
const H = 140
const CLAMP = 1200 // beyond this the shape stops telling you anything

interface Props {
  evals: number[]
  moments: KeyMoment[]
}

function y(cp: number): number {
  const clamped = Math.max(-CLAMP, Math.min(CLAMP, cp))
  return H / 2 - (clamped / CLAMP) * (H / 2)
}

export function EvalGraph({ evals, moments }: Props) {
  if (evals.length === 0) return null
  const x = (i: number) => (i / Math.max(1, evals.length - 1)) * W

  const line = evals.map((cp, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(cp)}`).join(' ')
  const area = `${line} L${W},${H / 2} L0,${H / 2} Z`

  return (
    <svg className="evalgraph" viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Evaluation over the course of the game, from White's point of view">
      <rect x={0} y={0} width={W} height={H / 2} className="eg-blackzone" />
      <rect x={0} y={H / 2} width={W} height={H / 2} className="eg-whitezone" />
      <path d={area} className="eg-area" />
      <path d={line} className="eg-line" />
      <line x1={0} y1={H / 2} x2={W} y2={H / 2} className="eg-axis" />
      {moments.map((m) => (
        <g key={m.ply}>
          <line x1={x(m.ply - 1)} y1={0} x2={x(m.ply - 1)} y2={H} className="eg-mark" />
          <circle cx={x(m.ply - 1)} cy={y(m.cp_after)} r={4}
                  className={`eg-dot ${m.classification}`} />
        </g>
      ))}
    </svg>
  )
}
