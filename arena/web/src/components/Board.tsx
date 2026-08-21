/**
 * The board. chessground with the cburnett set — the Lichess board, because §12 says
 * familiar beats clever. Arrows come from the threat layer (§8.3).
 */

import { useEffect, useRef } from 'react'
import { Chessground } from 'chessground'
import type { Api } from 'chessground/api'
import type { Key } from 'chessground/types'

interface Props {
  fen: string
  lastMove: [string, string] | null
  arrows: string[]
  hanging: string[]
  showArrows: boolean
  orientation?: 'white' | 'black'
}

export function Board({
  fen, lastMove, arrows, hanging, showArrows, orientation = 'white',
}: Props) {
  const element = useRef<HTMLDivElement>(null)
  const api = useRef<Api | null>(null)

  useEffect(() => {
    if (!element.current) return
    api.current = Chessground(element.current, {
      fen,
      orientation,
      viewOnly: true,
      coordinates: true,
      animation: { enabled: true, duration: 180 },
      drawable: { enabled: false, visible: true },
    })
    return () => {
      api.current?.destroy()
      api.current = null
    }
    // Built once; every later change goes through set() so animation is preserved.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    api.current?.set({
      fen,
      orientation,
      lastMove: (lastMove ?? undefined) as Key[] | undefined,
    })
  }, [fen, lastMove, orientation])

  useEffect(() => {
    const shapes = []
    if (showArrows) {
      for (const uci of arrows) {
        if (uci && uci.length >= 4) {
          shapes.push({
            orig: uci.slice(0, 2) as Key,
            dest: uci.slice(2, 4) as Key,
            brush: 'blue',
          })
        }
      }
      for (const square of hanging) {
        shapes.push({ orig: square as Key, brush: 'red' })
      }
    }
    api.current?.setShapes(shapes)
  }, [arrows, hanging, showArrows])

  return <div ref={element} className="board" />
}
