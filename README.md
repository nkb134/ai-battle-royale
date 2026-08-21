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

Phases 0, 1 and 2 are built: the headless match engine with a real clock, Stockfish
annotation and the post-match report, and the stream UI. Sound, faces and taunts
(phases 3 to 5) are not written yet, so the player boxes show placeholder squares.

Models available: Gemini 2.5 Pro, Flash and Flash-Lite, and gpt-oss 120b/20b, all on
Vertex. Claude is configured but inactive — it is enabled on Vertex yet sits at zero
quota, so requests return 429 until a quota increase is granted.

## Running it

```bash
make setup                        # venv, deps, Stockfish check, db init
make test
make match ARGS="--white mock-fast --black mock-drifted --tc 15+10"
```

`mock-*` models play locally with no API calls, which is what the test suite uses. To
use real models, authenticate and calibrate:

```bash
gcloud auth application-default login
cp arena.local.yaml.example arena.local.yaml   # then put your GCP project in it
make calibrate MODEL=gemini-2.5-flash
```

Calibration is required. The pacing controller needs a measured `tokens_per_sec` and
refuses to guess one.

## Reports

```bash
make analyze GAME=<match_id>     # rebuilds a full report from the stored PGN
make analyze-all
```

The report leads with ACPL in panic mode against ACPL for the rest of the game. That
comparison is the point of the clock system: it is where you see whether being forced
to reason less actually made a model play worse.

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
