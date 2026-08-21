/**
 * The move list. SAN for display, UCI kept underneath (§13). Classification colours
 * are among the only saturated things on the page (§12).
 */

import { useEffect, useRef } from 'react'
import type { MoveRow } from '../matchState'

interface Props {
  moves: MoveRow[]
  currentPly: number | null
  onSeek?: (ply: number) => void
}

function pairs(moves: MoveRow[]): [MoveRow | undefined, MoveRow | undefined][] {
  const out: [MoveRow | undefined, MoveRow | undefined][] = []
  for (let i = 0; i < moves.length; i += 2) out.push([moves[i], moves[i + 1]])
  return out
}

function Cell({ move, current, onSeek }: {
  move: MoveRow | undefined
  current: boolean
  onSeek?: (ply: number) => void
}) {
  if (!move) return <span className="move empty" />
  const classes = ['move', move.classification ?? '', current ? 'current' : '']
  const flags = [
    move.panic ? 'panic' : '',
    move.retryCount ? `${move.retryCount} illegal` : '',
    move.forcedRandom ? 'forced random' : '',
  ].filter(Boolean)

  return (
    <span
      className={classes.filter(Boolean).join(' ')}
      onClick={onSeek ? () => onSeek(move.ply) : undefined}
      title={[
        `${move.uci}`,
        move.cpLoss !== undefined ? `${move.cpLoss}cp lost` : '',
        `${(move.elapsedMs / 1000).toFixed(1)}s`,
        ...flags,
      ].filter(Boolean).join(' · ')}
    >
      {move.san}
      {move.classification === 'brilliant' && <sup className="mark">!!</sup>}
      {move.classification === 'blunder' && <sup className="mark">??</sup>}
      {move.panic && <sup className="mark panic-mark">⏱</sup>}
      {move.retryCount > 0 && <sup className="mark illegal-mark">×{move.retryCount}</sup>}
    </span>
  )
}

export function MoveList({ moves, currentPly, onSeek }: Props) {
  const bottom = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'nearest' })
  }, [moves.length])

  return (
    <div className="movelist">
      <div className="movelist-scroll">
        {pairs(moves).map(([white, black], i) => (
          <div className="movepair" key={i}>
            <span className="movenum">{i + 1}.</span>
            <Cell move={white} current={white?.ply === currentPly} onSeek={onSeek} />
            <Cell move={black} current={black?.ply === currentPly} onSeek={onSeek} />
          </div>
        ))}
        <div ref={bottom} />
      </div>
    </div>
  )
}
