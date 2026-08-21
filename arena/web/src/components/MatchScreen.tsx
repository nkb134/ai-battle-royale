/**
 * The stream layout (§12): player box, board with the eval bar down one side and the
 * move list down the other, player box.
 */

import { Board } from './Board'
import { EvalBar } from './EvalBar'
import { MoveList } from './MoveList'
import { PlayerBox } from './PlayerBox'
import { isQualified, type MatchState } from '../matchState'
import { material } from '../material'

const BOARD_PX = 512

interface Props {
  state: MatchState
  initialMs: number | null
  showArrows: boolean
  onToggleArrows: () => void
  onBack: () => void
  controls?: React.ReactNode
  banner?: React.ReactNode
}

export function MatchScreen({
  state, initialMs, showArrows, onToggleArrows, onBack, controls, banner,
}: Props) {
  const last = state.moves.at(-1)
  const { whiteCaptured, blackCaptured, edge } = material(state.fen)

  return (
    <div className="match">
      <header className="match-header">
        <button className="link" onClick={onBack}>← All matches</button>
        <span className="match-title">
          {state.white} <span className="vs">vs</span> {state.black}
          <span className="tc">{state.timeControl}</span>
        </span>
        <label className="toggle">
          <input type="checkbox" checked={showArrows} onChange={onToggleArrows} />
          Threat arrows
        </label>
      </header>

      {banner}

      <PlayerBox
        side="black"
        name={state.black}
        clockMs={state.clockBlack}
        initialMs={initialMs}
        active={state.thinking === 'black'}
        thinking={state.thinking === 'black'}
        tokenBudget={state.tokenBudget}
        captured={blackCaptured}
        materialEdge={-edge}
        taunt={state.taunt?.side === 'black' ? state.taunt.text : null}
      />

      <div className="match-middle">
        <EvalBar cp={state.cp} height={BOARD_PX} />
        <div className="board-column">
          <Board
            fen={state.fen}
            lastMove={state.lastMove}
            arrows={state.arrows}
            hanging={state.hanging}
            showArrows={showArrows}
          />
          <div className="callout">
            {last ? (
              <>
                <strong>{last.san}</strong>
                {last.classification && (
                  <span className={`chip ${last.classification}`}>
                    {last.classification}
                  </span>
                )}
                {last.cpLoss !== undefined && last.cpLoss > 0 && (
                  <span className="muted">{last.cpLoss}cp lost</span>
                )}
                <span className="muted">{(last.elapsedMs / 1000).toFixed(1)}s</span>
                {last.panic && <span className="chip panic">panic</span>}
                {last.retryCount > 0 && (
                  <span className="chip illegal">
                    {last.retryCount} illegal {last.retryCount === 1 ? 'try' : 'tries'}
                  </span>
                )}
                {last.forcedRandom && (
                  <span className="chip illegal">random move forced</span>
                )}
              </>
            ) : (
              <span className="muted">Starting position</span>
            )}
          </div>
          {controls}
        </div>
        <MoveList moves={state.moves} currentPly={last?.ply ?? null} />
      </div>

      <PlayerBox
        side="white"
        name={state.white}
        clockMs={state.clockWhite}
        initialMs={initialMs}
        active={state.thinking === 'white'}
        thinking={state.thinking === 'white'}
        tokenBudget={state.tokenBudget}
        captured={whiteCaptured}
        materialEdge={edge}
        taunt={state.taunt?.side === 'white' ? state.taunt.text : null}
      />

      {state.result && (
        <div className={`result ${isQualified(state.termination, state.adjudicated) ? 'qualified' : ''}`}>
          <strong>{state.result}</strong>
          <span>{state.termination?.replace(/_/g, ' ')}</span>
          {isQualified(state.termination, state.adjudicated) && (
            <em>not a clean finish — see how it ended</em>
          )}
        </div>
      )}
    </div>
  )
}
