# Contributing

Thanks for considering a contribution. firm-bot is meant to be the
easiest way to ship a citation-grounded chatbot over a firm's
private documents.

## Ground rules

1. **Data isolation is sacred.** Never change the per-firm data layout
   in a way that could leak chunks between firms. The Chroma collection
   name, the BM25 pickle, and the filesystem root must remain
   per-`FirmConfig.slug`.
2. **Citations are mandatory.** Any PR that relaxes the
   "every claim cites a source" invariant will be closed.
3. **Local-first by default.** Anything that ships data off-machine
   needs a clear, opt-in flag.
4. **No bare `except:` clauses.** Use specific exception types.
5. **No silent failures.** If an extractor returns 0 documents from a
   file, the operator must hear about it.

## Development setup

```bash
git clone https://github.com/firm-bot/firm-bot
cd firm-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The dev extra installs `pytest`, `pytest-cov`, `ruff`, `mypy`,
`respx`.

## Tooling

```bash
ruff check firm_bot eval tests     # lint
ruff format --check firm_bot eval tests  # format check
mypy firm_bot eval                 # type-check
pytest tests --cov=firm_bot         # test (60%+ coverage today)
```

CI runs the same four commands on macOS + ubuntu × Python 3.11/3.12/3.13.

## Adding a new extractor

The extractor protocol is implicit:

```python
def extract_<format>(path: Path) -> list[Document]:
    """..."""
```

To add a new format (e.g. `.html`):

1. Implement `firm_bot/ingest/<format>.py` returning `list[Document]`.
2. Add the suffix to `SUPPORTED_SUFFIXES` in
   `firm_bot/ingest/common.py` and add a branch in `dispatch()`.
3. Add a test in `tests/test_ingest_<format>.py` covering at least:
   happy path, malformed file, empty file.
4. Update [Supported formats](getting-started.md) in the README.

## Adding a new retrieval signal

Hybrid retrieval uses BM25 + dense + RRF. If you want to add a third
signal (e.g. cross-encoder reranker, knowledge-graph expansion):

1. Implement the new search under `firm_bot/retrieve/<signal>.py`
   returning a list of `(chunk_id, score, rank)` like the existing
   `bm25_search` and `dense_search`.
2. Add a weight to `RootConfig` (`<signal>_weight`).
3. Wire it into `hybrid_search()` with its own RRF contribution.
4. Add a test that compares the new signal vs the existing two on a
   small fixture.

## PR checklist

- [ ] `ruff check firm_bot eval tests` is clean
- [ ] `mypy firm_bot eval` is clean
- [ ] `pytest tests --cov=firm_bot` passes and coverage has not dropped
- [ ] At least one test added for the new behaviour
- [ ] README / docs updated if user-facing surface changed
- [ ] CHANGELOG.md updated (under "Unreleased")
- [ ] Commits describe what is IN them, not what comes next

## Reporting a security issue

See [Security](security.md). Do not file a public issue for
vulnerabilities that affect firm data confidentiality.
