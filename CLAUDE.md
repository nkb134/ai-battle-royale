# CLAUDE.md

Project instructions for **Arena** — a pet project where you pick two LLMs and a time control, hit start, and watch them play chess in a stream-style interface with live Stockfish eval, pixel-art model faces, taunts and sound.

Read this file fully before writing code. When something here conflicts with a default or a habit, this file wins. If a rule in here is wrong or impossible, say so and propose a change rather than quietly working around it.

---

## 1. What this is

A single-player web app, run locally. The user configures a match, watches it play out live, and gets a post-match report. It should feel like watching a chess stream, not like reading a benchmark.

**Setup screen** works like chess.com: pick White, pick Black, pick a time control, start.

**Match screen** is a stream layout: familiar board in the centre, a player box above and below with a pixel-art face, name, clock and captured pieces, an eval bar down one side, a move list down the other. Faces react. Thought bubbles and taunts appear. Sounds play on move, capture, check and low time.

Four things carry the project, and every decision should protect them:

1. **The board feels familiar.** Standard piece set, standard colours, standard sounds. Nothing clever.
2. **The clock is real.** Models are told how much time they have and are made to play faster when short. See §6, this is the most interesting engineering here.
3. **The chess is legible.** Eval bar, move classification, threat arrows, post-match report.
4. **The models have personality.** Pixel faces, reactions, taunts.

### Non-goals

- **No betting, odds, wagering, staking, or points with cash value.** This is a pet project on GitHub and stays that way. If a feature only makes sense as a step toward a betting product, do not build it.
- No accounts, no login, no cloud hosting in v1.
- No human-vs-AI mode in v1.
- No mobile layout in v1. Desktop web only.
- Not a public benchmark. No "official" or "canonical" language in the UI.

---

## 2. Stack

Pinned. Do not substitute without asking.

| Layer | Choice | Notes |
|---|---|---|
| Match engine | Python 3.11+, `python-chess` | Best legal-move and PGN handling that exists |
| Eval | Stockfish 17, local binary via UCI | No API cost |
| Storage | SQLite, WAL mode | One file, easy to back up and delete |
| API | FastAPI + WebSocket | Live push to the browser |
| Frontend | Vite + React + TypeScript | |
| Board | `chessground` + `cburnett` piece set | The Lichess board. Familiar, handles arrows and animation natively. Both GPL, keep the licence notices |
| Sound | Web Audio API, preloaded buffers | Not `<audio>` tags, latency is too variable |
| Faces | Pre-rendered pixel sprite sheets, CSS `steps()` | Never generate at runtime |
| Model calls | Provider SDKs behind one adapter interface | See §5.1 |

`uv` for Python, `pnpm` for the frontend.

### Commands

```bash
make setup                  # venv, deps, fetch Stockfish, init db, fetch board + sound assets
make serve                  # FastAPI + WebSocket on :8000
make web                    # Vite dev server on :5173
make dev                    # both, concurrently
make match ARGS="--white <id> --black <id> --tc 15+10"   # headless, no browser
make analyze GAME=<id>      # re-run analysis on a stored game
make calibrate MODEL=<id>   # measure tokens/sec, see §6.3
make test
```

---

## 3. Repo layout

```
arena/
  engine/
    match.py            # the match loop
    clock.py            # the chess clock, see §6
    pacing.py           # clock -> token budget controller
    adapters/           # one file per provider, all implement ModelAdapter
    prompts.py          # versioned templates
    adjudicate.py
  analysis/
    stockfish.py        # engine pool
    annotate.py         # classification, threats
    report.py
  persona/
    registry.py         # model -> face, palette, voice
    taunts.py           # off-clock banter, see §9.2
    sprites/
  api/
    server.py
    ws.py               # event protocol, see §7
  db/
    schema.sql
  web/
    src/
      components/{Board,PlayerBox,EvalBar,MoveList,SetupScreen}.tsx
      audio/
  data/
    arena.db
    games/              # PGN per game, eval in comments
    logs/               # JSONL per game, every prompt and raw response
    ASSETS.md           # licence record for every downloaded asset
```

---

## 4. Data model

- **models** — id, provider, model_string, display_name, face_id, palette, voice, tokens_per_sec, active
- **matches** — id, white, black, time_control, config_hash, started_at, ended_at, result, termination, ply_count
- **plies** — match_id, ply, fen_before, move_uci, move_san, legal, retry_count, cp_before, cp_after, cp_loss, classification, clock_ms_before, clock_ms_after, elapsed_ms, reasoning_tokens, token_budget, panic (bool)
- **taunts** — match_id, ply, speaker, text, trigger
- **ratings** — model_id, config_hash, rating, rd, volatility, games

Raw prompts and raw responses go to `data/logs/<match_id>.jsonl`, never truncated, never into SQLite.

---

## 5. Match engine

### 5.1 Adapter

```python
class ModelAdapter(Protocol):
    name: str
    model_string: str        # exact pinned dated version, never "latest"
    async def move(self, ctx: MoveContext) -> RawMoveResponse: ...
```

`MoveContext` carries: FEN, move history in SAN, side to move, **own clock ms, opponent clock ms, increment, token budget for this move**, and the retry counter. Nothing else. The adapter never sees the eval, the rating, or the opponent's reasoning.

Temperature 0. Provider seed where supported. Model strings pinned to dated versions. When a version is deprecated its rating freezes and the new version enters as a new row.

### 5.2 Prompt

Versioned in `prompts.py` as `PROMPT_V1` etc. Version SHA goes into `config_hash`. The prompt states the position, both clocks, the increment, and the token allowance, then asks for reasoning followed by a single move in a tag:

```
...reasoning, keep within your token budget...
<move>e2e4</move>
```

Parse the last `<move>` tag. Do not regex prose for algebraic notation.

### 5.3 Illegal moves

```yaml
legal_moves_provided: false   # default
max_retries: 2
on_exhausted: "random_legal"  # or "forfeit"
```

Default is off, because listing legal moves changes the test from "can it play chess" to "can it pick from a menu". Both are valid experiments, they are not comparable, so the flag is part of `config_hash`.

**Retries burn clock time.** Deliberate. An illegal move is a real cost, not a free do-over.

The retry prompt says only that the move was illegal. It must not hint at what is legal.

### 5.4 Adjudication

- **Resign:** eval worse than −900cp for the side to move across 6 consecutive plies.
- **Draw:** |eval| under 50cp for 30 consecutive plies with no capture and no pawn move.
- **Hard cap:** 250 plies.
- Standard rules first: checkmate, stalemate, threefold, fifty-move, insufficient material, **flag fall**.

Every adjudicated result is tagged and shown as such. Never present an adjudication as a clean win.

---

## 6. The clock

The most interesting subsystem in the project. Build it before any UI.

### 6.1 Mechanics

Fischer increment. The clock starts when the request is dispatched and stops when a legal move is accepted. **Wall clock, including network latency, including every illegal-move retry.** Increment is added after acceptance. At zero, that side loses on time, termination `flag_fall`, unless the opponent has insufficient mating material, in which case draw.

The server is the sole source of truth for time. The browser interpolates between WebSocket ticks for smooth display and resyncs on every event. Never let the frontend compute authoritative time.

### 6.2 The honest constraint

A model cannot decide to think faster. Its latency is roughly `tokens_generated / throughput + overhead`. So "play faster" means exactly one thing in practice: **generate fewer reasoning tokens.**

So the clock is enforced two ways at once, and both are needed:

1. **Told.** The prompt states remaining time for both sides and the token budget for this move. Some models will pace themselves. Most will ignore it.
2. **Enforced.** `max_tokens` on the request is set to the budget. This is what actually makes it work.

Do not pretend the first alone is sufficient. Log both `token_budget` and `reasoning_tokens` per ply so you can see which models actually respond to being told, which is a genuinely interesting result on its own.

### 6.3 Pacing controller

`pacing.py` converts remaining clock into a token budget.

```
expected_moves_left = max(12, 40 - move_number)
time_per_move_ms    = (remaining_ms - reserve_ms) / expected_moves_left + increment_ms
token_budget        = clamp(time_per_move_ms * tokens_per_sec / 1000, MIN, MAX)
```

`reserve_ms` defaults to 10% of the starting clock. `MIN` is 120 tokens, enough for a bare move with no reasoning. `MAX` is 4000.

`tokens_per_sec` is measured per model, never guessed. `make calibrate MODEL=x` runs 20 sample positions and stores a rolling median. Recalibrate weekly, providers change throughput without announcing it.

**Panic mode:** below 20% of the starting clock, hard-cap the budget at 250 tokens, append a line telling the model to move immediately with minimal reasoning, set `panic=true` on the ply, and emit a `low_time` event. Below 10%, cap at `MIN`.

### 6.4 Time controls

Human blitz does not work here. One frontier model call with reasoning is 5 to 30 seconds, so a 3+2 game is over before move 5 in a double flag fall.

Offer these, default `15+10`:

| Label | Clock | Notes |
|---|---|---|
| Quick | 10+5 | Small and fast models only |
| Standard | 15+10 | Default. Roughly 30 to 45 moves of real thinking |
| Long | 30+20 | Best chess, slow to watch |
| Casual | no clock, 3000 token cap per move | Pure quality, no time pressure |

The setup screen must warn when the chosen models' measured `tokens_per_sec` makes the chosen time control likely to flag. Compute it from calibration data, do not guess.

---

## 7. WebSocket protocol

One channel per match. Append-only events, each with a monotonic `seq` so the client can detect gaps and refetch.

```
match_start   { match_id, white, black, time_control, starting_fen }
thinking      { side, token_budget, clock_white, clock_black }
move          { ply, san, uci, fen_after, clock_white, clock_black, elapsed_ms,
                cp_after, cp_loss, classification, capture, check, retry_count, panic }
threats       { ply, best_reply_uci, hanging: [squares], arrows: [...] }
taunt         { side, text, trigger }
low_time      { side, remaining_ms }
match_end     { result, termination, report_url }
```

**Analysis must never block the move stream.** Emit `move` the instant the move is legal and applied, then emit `threats` when Stockfish finishes. The board never waits on the engine.

---

## 8. Analysis

### 8.1 Stockfish

Persistent engine pool. Open with `chess.engine.SimpleEngine.popen_uci()` and **always** close in a context manager or `finally`, or you will leak processes that quietly eat every core on the machine.

Fixed budget per ply, stored in `config_hash`. Default depth 18 or 200ms, whichever comes first. Never vary depth within a rating pool.

**Sign convention, get this right once and test it first:** store every eval in centipawns **from White's point of view**. `python-chess` returns a `PovScore`; call `.white()`, then `.score(mate_score=10000)`. Mates clamp to ±10000. This is the most common bug in projects like this. Write the test before writing anything that reads an eval.

### 8.2 Classification

`cp_loss` is the swing against the mover versus the engine's best move, from the mover's point of view.

| cp_loss | class | UI colour |
|---|---|---|
| 0–20 | best | green |
| 20–50 | good | neutral |
| 50–120 | inaccuracy | yellow |
| 120–300 | mistake | orange |
| 300+ | blunder | red |

Flag **brilliant** separately: a sacrifice by static exchange evaluation that is still the engine's top choice. Rare from LLMs, and the moment worth clipping.

### 8.3 Threats

Per position: engine best reply as an arrow, hanging pieces via SEE, available checks and captures for the side to move, and whether the last move created or ignored a threat. Arrows on by default, toggleable.

This is the layer that makes the stream readable to someone who is not a strong player. Prioritise it over visual polish.

### 8.4 Post-match report

Eval graph with annotated turning points. Top three key moments by cp swing, each with a diagram, the engine line, and one plain sentence about what happened. Per-side stats: ACPL, blunders, illegal moves, mean elapsed per move, mean reasoning tokens, and **ACPL in panic mode versus the rest of the game**. That last comparison is the payoff of the entire clock system, so give it prominent placement. Opening name via ECO, plus the ply where the game left book.

---

## 9. Faces, reactions and taunts

Start with **four models**. Get the feel right before adding more.

### 9.1 Faces

One original pixel-art face per model. 64x64 base, rendered at 128 or 192 with `image-rendering: pixelated`. Sprite sheet per face per state, animated with CSS `steps()`.

States: `idle`, `thinking`, `confident`, `worried`, `panic`, `blunder`, `brilliant`, `victory`, `defeat`, `illegal`.

Triggers come from the analysis layer and the clock, never from the model itself. An eval swing over 150cp in its favour fires `confident`. A blunder classification fires `blunder`. A `low_time` event fires `panic`. An illegal move fires `illegal`, which should be the funniest animation in the set. Debounce transitions to a 1.5s minimum so the face is not seizing on every ply.

**Rules:** original designs only, no resemblance to existing character IP, no provider logos, trademarks or brand colours on the faces. The model's real name goes as text in the player box. The face itself stays unbranded.

### 9.2 Taunts and thought bubbles

**Taunts are generated off the clock, on a side channel, by a separate cheap model.** Never on the playing model's request, never counted against its time, never blocking the move. If taunt generation is slow or fails, the match continues silently. This is non-negotiable, otherwise the banter corrupts the results.

Triggers: opponent blunders, own brilliant move, opponent enters low time, capture of a major piece, first move, resignation. Rate limit to one taunt per side per 4 plies.

The taunt generator gets the event and the stats only, never the game history, or it will invent a game that did not happen. One short line. Personality comes from a `voice` string in the registry, for example "smug and clipped" or "anxious, over-explains". Mild and playful. Nothing insulting beyond the chess.

Thought bubbles during `thinking` are a separate, simpler thing: a short static line drawn from a canned per-model pool. No API call.

---

## 10. Sound

Subtle. The reference is Lichess, not a mobile game.

- **move** — soft wooden click, around 40ms
- **capture** — heavier, clearly distinct from move
- **check** — short rising two-note
- **castle** — double click
- **promotion** — small chime
- **low time** — quiet tick from 20% of clock, once per second, never louder than the move sound
- **flag fall** — single low tone
- **match end** — short resolve, different for win and draw

Rules: preload every buffer at match start via Web Audio, never `<audio>` tags. Master volume defaults to 0.4 with a persistent mute toggle in the header. Never overlap two sounds within 50ms, queue or drop. No sound on taunts. No background music, ever.

Assets: CC0 or public domain only, or synthesize the simple ones with an oscillator. Record every asset's licence in `data/ASSETS.md`.

---

## 11. Ratings

Glicko-2, not Elo. With tens of games, rating deviation is the point. Always display as `1420 ± 180`, never a bare number. Under 30 games, mark provisional.

Rating pools are keyed on `config_hash`, which includes prompt version, `legal_moves_provided`, analysis depth and **time control**. The same model at 10+5 and at Casual are different entries. Do not merge pools.

Alongside rating, track ACPL, blunders per 100 plies, illegal moves per 100 plies, and mean time per move. At low sample sizes these say more than the rating does.

---

## 12. Frontend

**Setup screen.** Two model pickers with face previews, time control selector, an advanced panel for `legal_moves_provided` and max retries, start button. Warn on likely flag-fall combinations per §6.4.

**Match screen.** Stream layout:

```
+------------------------------------------------------+
|  [face]  Black model name        [clock]  [captured]  |
+--------+------------------------------------+--------+
|  eval  |                                    |  move  |
|  bar   |              board                 |  list  |
|        |                                    |        |
+--------+------------------------------------+--------+
|  [face]  White model name        [clock]  [captured]  |
+------------------------------------------------------+
```

The active side's player box is highlighted. Clock turns amber under 20%, red under 10%, with the tick sound. Thought bubble anchors to the thinking model's face. The last move's classification is called out under the board. Threat arrows drawn via chessground.

**Report screen.** Per §8.4.

Design: dark by default. The eval bar and the classification colours are the only saturated elements on the page, so the chess reads clearly. Board stays a standard familiar green or brown, no neon. Nothing animates unless it is reacting to a real event.

---

## 13. Conventions

- Python: `ruff`, `black`, type hints on public functions, `pytest`.
- TypeScript strict, no `any`.
- Conventional commits.
- All config in `arena.yaml`. Anything that can change a result belongs in config, and therefore in `config_hash`.
- Provider errors: exponential backoff, 3 attempts, then abort the match as `provider_error` and exclude it from ratings. Never substitute a move outside the §5.3 retry policy.
- Write the test before the fix for anything touching evals, sign conventions, clocks or rating maths.
- README states the licences for chessground, cburnett and every sound asset.

### Known traps

- Stockfish processes leak without a context manager.
- `PovScore` sign errors. See §8.1.
- SAN and UCI mixing. Store both, parse UCI, display SAN.
- Clock drift between server and browser. Server is authoritative, always.
- Streamed responses make token counting awkward. Count on completion from the usage field, never estimate.
- SQLite needs WAL or the live writer and the API reader will fight.
- Models shuffle pieces constantly, so threefold repetition is normal, not a bug.
- Provider rate limits bite well before token cost does.

---

## 14. Build order

Do not start a phase before the previous one's definition of done is met.

**Phase 0 — headless match with a real clock.** Two models, full game, legal move enforcement with retries costing time, pacing controller, flag fall, adjudication, PGN with eval comments, complete JSONL log.
*Done when:* 10 matches run unattended without a crash, at least one ends in a genuine flag fall, and the eval sign test passes.

**Phase 1 — analysis.** Stockfish annotation, classification, threats, post-match report.
*Done when:* `make analyze` regenerates a full report from a stored PGN.

**Phase 2 — the stream UI.** Setup screen, board, clocks, eval bar, move list, WebSocket events, threat arrows. Placeholder squares where the faces go.
*Done when:* a full match is watchable end to end in a browser, no console errors, no manual refresh, clocks visually matching the server.

**Phase 3 — sound.** Move, capture, check, low time, end.
*Done when:* it is pleasant to watch a whole game with sound on.

**Phase 4 — faces.** Four models, sprite sheets, state triggers, thought bubbles.

**Phase 5 — taunts.** Off-clock side channel per §9.2.

**Phase 6 — everything else.** More models, ratings across many games, clip export, other games. Do not touch this until 0 through 5 feel good.

---

## 15. When to push back

If asked to add betting, odds, staking or anything money-adjacent, refuse and point at §1. If asked to run taunt generation on the playing model's clock, to make retries free, to merge rating pools across different time controls, or to present an adjudicated or flagged result as a clean win, refuse and point at the relevant section. The point of the project is that the games are real, and a pet project has no excuse for faking them.

---

## 16. Distribution — GitHub and Pages

Decided after §1 was written. Where this section conflicts with the "no cloud hosting in v1"
non-goal, this section wins, and only to the extent stated here.

Repo: `nkb134/ai-battle-royale`, public. Public because GitHub Pages needs it on a free plan.

**The backend never leaves the machine.** Pages is a static file host — no server process, no
custom headers, no subprocess. FastAPI, `python-chess`, the Stockfish binary and SQLite all stay
local. Nothing in §2 is substituted to make Pages work.

### 16.1 Two modes, one SPA

The frontend built in Phase 2 ships a single bundle that runs in either mode.

**Replay mode** is the default and the only one a visitor gets. A finished match is written to
`arena/data/replays/<match_id>.json`, committed, and served by Pages. The viewer plays it back
through the full stream UI at the real recorded timings.

**Live mode** is opt-in and local. The same SPA points at `http://localhost:8000` and consumes
§7 events over WebSocket while `make serve` is running. Firefox has historically blocked a
`ws://localhost` socket opened from an HTTPS page, so this is a convenience for the author, never
a foundation. Replay mode must never depend on any part of it.

### 16.2 The replay file

§7 is already an append-only log with a monotonic `seq`. The replay file is exactly that event
list plus a header, so replay and live share one reducer in the client. Writing a second event
format, or letting the two drift, defeats the point.

**Replay stays honest, per §15.** It plays back real recorded `elapsed_ms`, real clock values and
real evals from a match that actually happened. It never simulates, re-times, or re-runs a match.
A replay of an adjudicated or flagged game is still tagged as such.

### 16.3 What is committed

Committed: source, `arena/data/games/*.pgn`, `arena/data/replays/*.json`,
`arena/data/reports/*.json`, `arena/data/eco/*.tsv`.

**Never committed:** `arena/data/logs/*.jsonl`, `arena/data/arena.db`, `arena.local.yaml`, or any
credential. The JSONL logs hold every raw prompt and response untruncated (§4) and the repo is
public. `.gitignore` enforces this and is not to be loosened.

### 16.4 Deploy

GitHub Actions builds `arena/web` and publishes to Pages on push to `main`. Vite `base` is set to
the repo path, and `404.html` mirrors `index.html` so client-side routes survive a refresh.
Deploying the workflow file needs the `workflow` scope on the gh token: `gh auth refresh -s workflow`.
