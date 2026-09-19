# firm-bot-sdk

Zero-dependency, synchronous Python client for the
[firm-bot](https://github.com/falcon-nest/firm-bot) HTTP API.

- **Stdlib only.** No `requests`, no `httpx`, no `pydantic`.
- Targets any **firm-bot ≥ 0.2.0** server.
- Strict type hints; ships a `py.typed` marker.
- Python 3.11+.

```bash
pip install firm-bot-sdk
```

## Quickstart

```python
from firm_bot_sdk import FirmBotClient, NotFoundError

client = FirmBotClient(
    base_url="http://localhost:8080",
    api_key="fb_your_api_key_here",
)

# 1. List firms
firms = client.list_firms()
for f in firms:
    print(f.slug, f.name)

# 2. Create a firm
cfg = client.create_firm(
    "acme-llp",
    "Acme LLP",
    system_prompt="You are Acme LLP's contract assistant.",
)

# 3. Ingest a corpus (uploads every file under ./corpus, then indexes)
result = client.ingest("acme-llp", "./corpus")
print(f"indexed {result.chunks_indexed} chunks")

# 4. Ask a question
resp = client.query("acme-llp", "What is the indemnification cap?", k=6)
print(resp.answer)
print("cited:", resp.cited)
print("confidence:", resp.confidence)

# 5. Read the audit log (JSON entries)
entries = client.get_audit_log("acme-llp", format="json")
for e in entries:
    print(e.timestamp, e.confidence, e.guard_summary)
```

## Error handling

The SDK raises a typed exception hierarchy rooted at
`FirmBotError`:

| Exception        | HTTP status         |
| ---------------- | ------------------- |
| `AuthError`      | 401 / 403           |
| `NotFoundError`  | 404                 |
| `ValidationError`| 400 / 422           |
| `RateLimitError` | 429                 |
| `ServerError`    | any 5xx             |
| `FirmBotError`   | network / unknown   |

```python
from firm_bot_sdk import FirmBotClient, NotFoundError

client = FirmBotClient("http://localhost:8080", api_key="fb_...")
try:
    cfg = client.get_firm("missing-slug")
except NotFoundError as e:
    print(f"firm not found at {e.path}: {e}")
```

## Audit log formats

`get_audit_log(format=...)` accepts:

- `"json"`  — returns a list of `AuditLogEntry` (default).
- `"csv"`   — returns a raw CSV string for SIEM import.
- `"jsonl"` — returns newline-delimited JSON.
- `"md"`    — returns a Markdown table.

```python
csv_text = client.get_audit_log("acme-llp", format="csv")
```

## Development

```bash
# from this directory (sdks/python/)
pip install -e ".[test]"
pytest tests -v
ruff check src tests
mypy --strict src
```

The test suite patches `urllib.request.urlopen` with a programmable
fake transport — no real network calls are made.

## License

MIT.
