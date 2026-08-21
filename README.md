# Arena

Pick two LLMs and a time control, hit start, and watch them play chess in a stream-style
interface with live Stockfish eval, pixel-art faces, taunts and sound.

It is a pet project. It is not a benchmark, and there is nothing official about the
numbers it produces.

## What makes it interesting

The clock is real. Models are told how much time they have, and are *made* to play
faster when short by capping the tokens they may spend reasoning. A model cannot decide
to think faster — its latency is roughly `tokens / throughput` — so the only honest
lever is generating less. Both the budget it was told and the tokens it actually spent
are logged for every move, which makes "does this model respond to being told to hurry"
a measurable question rather than a guess.

Retries after an illegal move burn clock. Adjudicated and flagged results are tagged as
such and never dressed up as clean wins.

## Status

Phase 0 (headless match with a real clock) is built. The stream UI is Phase 2 and not
yet written. See `CLAUDE.md` §14 for the build order.

## Running it

```bash
make setup                        # venv, deps, Stockfish check, db init
make test
make match ARGS="--white mock-fast --black mock-drifted --tc 15+10"
```

`mock-*` models play locally with no API calls. To use real models, set the ones you
want `active` in `arena.yaml`, authenticate, and calibrate:

```bash
gcloud auth application-default login
make calibrate MODEL=claude-vertex
```

Calibration is required. The pacing controller needs a measured `tokens_per_sec` and
refuses to guess one.

## Watching matches

Finished matches are written to `arena/data/replays/` and replayed by the web app at
**https://nkb134.github.io/ai-battle-royale/**.

The backend never leaves your machine. GitHub Pages is a static host, so it serves the
recorded event stream rather than running the engine. Replay is honest: it plays back
the real recorded timings, clocks and evals from a match that actually happened, and
never re-runs or re-times anything. Live watching is local only, via `make dev`.

## Licences

Arena is **GPL-3.0**. It links python-chess and bundles chessground, both GPL, so the
combined work is GPL and the notices stay in place:

| Component | Licence | Notes |
|---|---|---|
| [chessground](https://github.com/lichess-org/chessground) | GPL-3.0 | The Lichess board component |
| [cburnett piece set](https://github.com/lichess-org/lila/tree/master/public/piece/cburnett) | GPL-2.0 | Colin M.L. Burnett's pieces, via Lichess |
| [python-chess](https://github.com/niklasf/python-chess) | GPL-3.0 | Move generation, SAN/PGN |
| [Stockfish](https://stockfishchess.org/) | GPL-3.0 | Analysis engine, run as a separate process |

Sound assets are CC0 or public domain only, recorded individually in
[`arena/data/ASSETS.md`](arena/data/ASSETS.md).

Model faces are original artwork. No provider logos, trademarks or brand colours appear
on them.
