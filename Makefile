# firm-bot developer Makefile
#
# Usage:
#   make help           list targets
#   make install        install firm-bot in editable mode
#   make demo           bootstrap the sample firm (demo)
#   make dev            install + run sample firm + serve on :7860
#   make test           run the test suite
#   make lint           ruff + ruff format check
#   make typecheck      mypy --strict
#   make docs           build mkdocs site into site/
#   make docker         bring up the full stack via docker-compose
#   make docker-down    tear it down
#   make docker-logs    tail logs from both containers
#   make build          build sdist + wheel into dist/
#   make clean          remove caches and build artifacts
#
# Most users will only ever need: install demo dev test docker

# ---- config ------------------------------------------------------------

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
PORT ?= 7860
DATA_DIR ?= ./data
LLM_MODEL ?= qwen2.5-coder:1.5b-instruct

.PHONY: help install demo dev test lint typecheck docs docker docker-down docker-logs build clean all

help:  ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---- install -----------------------------------------------------------

install:  ## install firm-bot in editable mode (dev extras)
	$(PIP) install -e ".[dev]"

# ---- demo --------------------------------------------------------------

demo:  ## bootstrap the sample firm (creates "demo" + ingests samples)
	$(PYTHON) -m firm_bot.cli --data-dir $(DATA_DIR) demo init

demo-reset:  ## wipe and recreate the demo firm
	$(PYTHON) -m firm_bot.cli --data-dir $(DATA_DIR) demo init --reset

# ---- dev server --------------------------------------------------------

dev:  ## run firm-bot serve with the bundled demo firm
	$(PYTHON) -m firm_bot.cli --data-dir $(DATA_DIR) serve --port $(PORT)

# ---- tests -------------------------------------------------------------

test:  ## run the full test suite
	pytest tests -q

test-cov:  ## run tests with coverage report
	pytest tests -q --cov=firm_bot --cov-report=term-missing

test-load:  ## run the load benchmark (skipped by default in CI)
	FIRM_BOT_RUN_LOAD_BENCH=1 pytest tests/test_load.py -v

# ---- benchmarks --------------------------------------------------------

# Pure in-memory retrieval benchmark — no Ollama needed. Compares
# structure-aware chunker vs naive sliding-window over the 30-contract
# curated corpus and 59 questions in eval/compare_fixture.json.
bench-compare:  ## retrieval benchmark (firm_bot chunker vs naive), pure in-memory
	$(PYTHON) -m eval.compare --markdown --out eval/results/compare-latest.json

bench-compare-full:  ## retrieval benchmark with the explicit corpus+fixture paths
	$(PYTHON) -m eval.compare \
		--corpus eval/compare_corpus \
		--fixture eval/compare_fixture.json \
		--markdown \
		--out eval/results/compare-latest.json

# End-to-end benchmark — needs a live Ollama. Use --limit N to keep it fast.
bench-e2e:  ## end-to-end benchmark (needs Ollama running)
	$(PYTHON) -m eval.eval_e2e --limit 10 --markdown

bench-load:  ## concurrent load benchmark (FIRM_BOT_RUN_LOAD_BENCH=1)
	FIRM_BOT_RUN_LOAD_BENCH=1 pytest tests/test_load.py -v -s

bench: bench-compare  ## alias for the default benchmark

# ---- lint / typecheck --------------------------------------------------

lint:  ## ruff check + format check on production code
	ruff check firm_bot eval tests
	ruff format --check firm_bot eval tests

fix:  ## ruff auto-fix on production code
	ruff check --fix firm_bot eval tests

typecheck:  ## mypy --strict on firm_bot
	mypy --strict firm_bot

# ---- docs --------------------------------------------------------------

docs:  ## build mkdocs site into site/
	mkdocs build

docs-serve:  ## mkdocs serve on :8000
	mkdocs serve

# ---- docker ------------------------------------------------------------

docker:  ## bring up the full stack (firm-bot + Ollama) via docker compose
	docker compose up -d
	@echo "firm-bot: http://localhost:$(PORT)  (model auto-pulls on first boot)"

docker-down:  ## stop + remove the stack
	docker compose down

docker-logs:  ## tail logs from both containers
	docker compose logs -f

docker-rebuild:  ## rebuild images from scratch
	docker compose build --no-cache

# ---- package -----------------------------------------------------------

build:  ## build sdist + wheel into dist/
	$(PIP) install --quiet build
	$(PYTHON) -m build --sdist --wheel

publish-test: build  ## upload to TestPyPI (requires TWINE_PASSWORD env)
	twine upload --repository testpypi dist/*

publish: build  ## upload to PyPI (requires TWINE_PASSWORD env)
	twine upload dist/*

# ---- housekeeping ------------------------------------------------------

clean:  ## remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov build dist site
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

all: lint typecheck test  ## full local pre-push gate
