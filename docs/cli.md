# CLI reference

firm-bot ships a single command-line entry point: `firm-bot`. All
subcommands take `--data-dir <path>` to override the data directory;
the default is `$FIRM_BOT_DATA_DIR` or `./data`.

## Top-level

```
firm-bot [--data-dir DIR] [--verbose] {firm,ingest,query,query_stream,eval,migrate,watch,serve}
```

| Flag           | Description                                    |
|----------------|------------------------------------------------|
| `--data-dir`   | Override data directory (default `./data`)     |
| `--verbose -v` | Increase log verbosity (repeatable)            |

## `firm-bot firm`

Manage firms.

```
firm-bot firm create --slug <s> --name <n> [--system-prompt ...] [--llm-model ...] [--contact-email ...]
firm-bot firm list
firm-bot firm config <slug> [--set-system-prompt-file ...] [--set-llm-model ...] [--set-name ...]
```

## `firm-bot ingest <slug>`

Scan the firm's `source/` directory, extract, chunk, embed, index.

Idempotent by default. With `incremental_indexing=True` (the default),
only files whose content SHA-256 has changed are re-processed.
Pass `--force` to re-ingest everything.

```
firm-bot ingest <slug> [--force]
```

## `firm-bot query <slug> "..."`

Ask a single question from the CLI.

```
firm-bot query <slug> <question> [--no-guard] [--k N]
```

| Flag       | Description                                |
|------------|--------------------------------------------|
| `--no-guard` | Skip the citation guard LLM               |
| `--k`       | Override `answer_k` for this query         |

## `firm-bot eval <slug> --fixture cases.json`

Run a faithfulness eval over a JSON fixture.

```
firm-bot eval <slug> --fixture <path>
```

Fixture format:

```json
{
  "cases": [
    {
      "question": "What's the cap on liability?",
      "expected_sources": ["acme_msa.pdf"],
      "expected_keywords": ["twelve (12) months", "fees paid"]
    }
  ]
}
```

## `firm-bot migrate <slug>`

Upgrade a firm's `config.yaml` to the current schema. New fields get
sensible defaults; your values are preserved. Original is backed up to
`config.yaml.bak`.

## `firm-bot watch <slug>`

Auto re-ingest when files in `source/` change.

```
firm-bot watch <slug> [--debounce 2.0]
```

## `firm-bot serve`

Run the FastAPI server (UI + HTTP API).

```
firm-bot serve [--host 127.0.0.1] [--port 7860] [--reload]
```

For development, `--reload` enables uvicorn's autoreload on file
changes. For production, run behind a reverse proxy that adds auth
(see [Security](security.md)).
