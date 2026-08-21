.PHONY: setup serve web web-build replays dev match analyze calibrate test lint fmt

PY := .venv/bin/python

setup:
	uv venv --python 3.13
	uv pip install -e ".[dev]"
	@command -v stockfish >/dev/null 2>&1 && echo "stockfish: $$(command -v stockfish)" \
		|| { echo "stockfish not found."; \
		     echo "  macOS:  brew install stockfish"; \
		     echo "  linux:  apt-get install stockfish"; exit 1; }
	$(PY) -m arena.db.store --init
	@echo "setup complete"

serve:
	$(PY) -m arena.api.server

# Replays live in arena/data and are copied into the web app, never duplicated in the
# repo (§16.2). The Pages workflow does the same copy at build time.
replays:
	$(PY) -m arena.cli index
	mkdir -p arena/web/public/replays
	cp arena/data/replays/*.json arena/web/public/replays/

web: replays
	pnpm --dir arena/web install && pnpm --dir arena/web dev

web-build: replays
	pnpm --dir arena/web install && pnpm --dir arena/web build

dev:
	$(MAKE) -j2 serve web

match:
	$(PY) -m arena.cli match $(ARGS)

analyze:
	$(PY) -m arena.cli analyze --game $(GAME)

calibrate:
	$(PY) -m arena.cli calibrate --model $(MODEL)

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check arena tests

fmt:
	.venv/bin/black arena tests && .venv/bin/ruff check --fix arena tests
