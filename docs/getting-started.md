# Getting started

## Install

```bash
pip install firm-bot
```

firm-bot supports Python 3.11+. The install pulls in:

- `fastapi`, `uvicorn` — HTTP API server
- `chromadb`, `rank-bm25`, `sentence-transformers` — retrieval
- `pypdf`, `pytesseract`, `python-docx` — document extractors
- `httpx`, `pydantic`, `watchdog` — supporting infrastructure

### Optional extras

- `pip install firm-bot[embed-fastembed]` — adds `fastembed` as a faster
  alternative to `sentence-transformers` for the embedding step.

### System dependencies

The OCR fallback for scanned PDFs needs Tesseract + Poppler:

```bash
# macOS
brew install tesseract poppler

# Ubuntu / Debian
sudo apt-get install -y tesseract-ocr poppler-utils

# Alpine
apk add tesseract-ocr poppler-utils
```

## Pull the LLM models

firm-bot is designed for local LLMs via [Ollama](https://ollama.com).
Pull the two models the defaults assume:

```bash
ollama pull qwen2.5-coder:14b    # answer model — ~9 GB
ollama pull qwen2.5-coder:7b     # citation guard — ~4.7 GB
```

Smaller models (3B, 1.5B) work but with reduced citation quality.
The 7B model is the smallest that produces coherent bracket citations.

## Create a firm

```bash
firm-bot firm create --slug demo --name "Demo LLP"
```

This creates:

```
data/firms/demo/
├── config.yaml         # per-firm settings (system prompt, model overrides)
├── source/             # ← drop files here
├── processed/          # extracted text (debug view)
└── store/              # Chroma + BM25 indexes
```

## Drop a contract, ingest, ask

```bash
cp ~/Documents/sample-contract.pdf ./data/firms/demo/source/
firm-bot ingest demo
firm-bot query demo "What's the cap on liability?"
```

You'll see something like:

```json
{
  "answer": "The cap on liability in the MSA is the fees paid by Acme Corp to
             Demo LLP in the twelve (12) months preceding the event giving
             rise to the claim. [acme_msa.pdf:p.1]",
  "cited": ["acme_msa.pdf:p.1"],
  "hits": [...]
}
```

## Run the web UI

```bash
firm-bot serve --port 7860
# open http://127.0.0.1:7860
```

The UI supports drag-drop upload, source pane on citation click, and
multi-firm switching. See [Architecture](architecture.md) for details
on the chat flow.

## What to read next

- [CLI](cli.md) — every subcommand firm-bot ships with
- [Configuration](configuration.md) — tunables in `data/config.yaml`
- [Deployment](deployment.md) — Docker, self-host, multi-tenant
- [Benchmarks](benchmarks.md) — measured numbers on a 30-document corpus
- [Security](security.md) — threat model and what's out of scope
