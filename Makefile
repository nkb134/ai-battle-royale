.PHONY: setup serve web dev match analyze calibrate test lint fmt

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

web:
	cd arena/web && pnpm install && pnpm dev

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
