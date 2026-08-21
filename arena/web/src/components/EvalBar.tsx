/**
 * The eval bar. Centipawns from White's point of view, always (§8.1).
 *
 * The mapping to bar height is deliberately non-linear: a +1 advantage should look
 * meaningfully different from +2, while +9 and +10 need not.
 */

const MATE = 10000

interface Props {
  cp: number
  height: number
}

function whiteShare(cp: number): number {
  if (cp >= MATE) return 1
  if (cp <= -MATE) return 0
  return 1 / (1 + Math.exp(-cp / 320))
}

function label(cp: number): string {
  if (cp >= MATE) return 'M'
  if (cp <= -MATE) return '-M'
  const pawns = cp / 100
  return `${pawns > 0 ? '+' : ''}${pawns.toFixed(1)}`
}

export function EvalBar({ cp, height }: Props) {
  const share = whiteShare(cp)
  return (
    <div className="evalbar" style={{ height }} title={`${cp}cp (White's point of view)`}>
      <div className="evalbar-black" style={{ height: `${(1 - share) * 100}%` }} />
      <div className="evalbar-white" style={{ height: `${share * 100}%` }} />
      <span className={`evalbar-label ${cp >= 0 ? 'on-white' : 'on-black'}`}>
        {label(cp)}
      </span>
    </div>
  )
}
