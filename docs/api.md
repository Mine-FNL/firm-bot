# HTTP API

All endpoints take JSON request bodies and return JSON responses
(unless noted). Errors are returned as `{"detail": "..."}` with
appropriate HTTP status codes.

## Health & UI

```
GET  /             → single-page chat UI (HTML)
GET  /healthz      → liveness probe (200 OK)
```

## Firm management

```
GET    /v1/firms                          # list firms
POST   /v1/firms                          # create a firm
GET    /v1/firms/{slug}/config            # read firm config
PATCH  /v1/firms/{slug}/config            # update firm config
GET    /v1/firms/{slug}/stats             # chunk + file counts
```

### `POST /v1/firms`

Request:

```json
{
  "slug": "acme-llp",
  "name": "Acme LLP",
  "system_prompt": "",
  "llm_model": "",
  "contact_email": ""
}
```

Response: 201 with the created `FirmConfig` fields.

## Document management

```
POST   /v1/firms/{slug}/upload     # upload a single file to source/
POST   /v1/firms/{slug}/ingest     # scan source/, extract, chunk, embed, index
```

### `POST /v1/firms/{slug}/ingest`

Query parameter:

- `force=true` — re-ingest all files (bypass incremental indexing)

Response:

```json
{
  "stats": {
    "files_total": 3,
    "files_failed": 0,
    "documents_total": 12,
    "pages_with_ocr": 0,
    "files_skipped": 0
  },
  "chunks_indexed": 47,
  "skipped": 0
}
```

## Query

```
POST   /v1/firms/{slug}/query          # non-streaming, returns full answer
POST   /v1/firms/{slug}/query/stream   # SSE stream of token deltas
```

### `POST /v1/firms/{slug}/query`

Request:

```json
{
  "question": "What's the cap on liability?",
  "history": [],
  "run_guard": true,
  "k": null
}
```

Response:

```json
{
  "answer": "The cap on liability in the MSA is... [acme_msa.pdf:p.1]",
  "cited": ["acme_msa.pdf:p.1"],
  "hits": [
    {
      "chunk_id": "abc123:0",
      "marker": "acme_msa.pdf:p.1",
      "score": 0.016,
      "bm25_rank": 0,
      "dense_rank": 0,
      "preview": "Section 4.2 — Limitation of Liability..."
    }
  ],
  "issues": [],
  "summary": "ok",
  "model": "qwen2.5-coder:14b",
  "judge_model": "qwen2.5-coder:7b"
}
```

### `POST /v1/firms/{slug}/query/stream`

Server-Sent Events of token deltas:

```
event: meta
data: {"hits": [...], "model": "..."}

event: token
data: {"delta": "The cap"}

event: token
data: {"delta": " on liability..."}

event: done
data: {"answer": "full text", "cited": [...], "issues": []}
```

The first `meta` event carries the retrieved hits so the UI can
render the citation pane before tokens arrive. `token` events fire
as Ollama generates. `done` carries the assembled answer.

Streaming skips the post-hoc citation guard. For the audit trail,
use the non-streaming endpoint.

## Eval

```
POST   /v1/firms/{slug}/eval
```

Request:

```json
{
  "cases": [
    {
      "question": "What's the cap on liability?",
      "expected_sources": ["acme_msa.pdf"],
      "expected_keywords": ["twelve (12) months"]
    }
  ]
}
```

Response: aggregate + per-row metrics. See [Benchmarks](benchmarks.md).

## Error codes

| Status | Meaning                                                |
|--------|--------------------------------------------------------|
| 400    | Empty question or invalid slug                         |
| 404    | Unknown firm                                           |
| 409    | Firm has no indexed chunks; call `/ingest` first       |
| 422    | Pydantic schema validation failed                       |
| 500    | Internal error (check server logs)                     |
