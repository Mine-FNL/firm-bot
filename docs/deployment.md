# Deployment

## Single-machine (typical)

The simplest deployment: one machine running Ollama + firm-bot.

```bash
# 1. Install Ollama and pull models
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5-coder:14b
ollama pull qwen2.5-coder:7b

# 2. Install firm-bot
pip install firm-bot

# 3. Run the server (binds 0.0.0.0:7860 inside the container)
firm-bot serve --host 0.0.0.0 --port 7860
```

Open `http://<machine>:7860` for the web UI.

## Docker (single container, system Ollama)

The shipped `Dockerfile` installs firm-bot + OCR deps + tesseract on
top of `python:3.12-slim`:

```bash
docker build -t firm-bot:latest .
docker run --rm -p 7860:7860 \
    -v $(pwd)/data:/app/data \
    -e FIRM_BOT_OLLAMA_HOST=http://host.docker.internal:11434 \
    firm-bot:latest
```

The `host.docker.internal` host name lets the container reach Ollama
running on the host. On Linux you may need `--add-host=host.docker.internal:host-gateway`.

## Docker Compose (firm-bot + Ollama side-by-side)

The shipped `docker-compose.yml` brings up both services with a
persistent Ollama volume:

```bash
docker compose up -d
open http://localhost:7860
```

Ollama listens on `:11434` (also exposed to the host so you can pull
models from the host CLI):

```bash
ollama pull qwen2.5-coder:14b
```

## Multi-firm on one machine

Each firm is a slug-scoped directory under `data/firms/`. Different
firms never share data. Add as many as you want:

```bash
firm-bot firm create --slug acme --name "Acme LLP"
firm-bot firm create --slug globex --name "Globex Industries"
firm-bot firm create --slug wayne --name "Wayne Enterprises"
```

Each gets its own:

- `config.yaml` — per-firm system prompt, model overrides, redaction
- `source/` — operator drops files here
- `store/` — Chroma collection, BM25 index, indexed-files manifest
- `processed/` — extracted text (debug view)

## Hardening for public deployment

firm-bot v0.1 ships without auth — it's designed for closed deployments
on a firm's internal network. If you must expose it to the internet:

1. Put a reverse proxy (nginx, Caddy) in front that adds authentication.
   HTTP Basic at minimum, OIDC preferred.
2. Enable HTTPS via Let's Encrypt.
3. Restrict `/v1/firms/{slug}/upload` and `/v1/firms/{slug}/ingest` to
   operator roles; expose `/v1/firms/{slug}/query` to end users with
   per-user rate limits.
4. Set `client_max_body_size 100M` at the proxy.
5. Run firm-bot as a non-privileged user.

First-class auth (token / API key) is on the v0.2 roadmap.

## Resource sizing

Per [Performance](security.md):

| Component             | RAM (warm)  |
|-----------------------|-------------|
| Sentence-transformers (MiniLM) | ~300 MB |
| Ollama 14B Q4_K_M     | ~9 GB       |
| Ollama 7B Q4_K_M      | ~5 GB       |
| Chroma (per firm, 1k chunks) | ~50 MB |
| BM25 (per firm, 1k chunks)   | ~10 MB |

A 16 GB M4 can comfortably run the answer model + judge + embeddings
simultaneously. A 32 GB machine gives you headroom.

## Backup

Each firm's state lives entirely under `data/firms/<slug>/`. To back
up a firm:

```bash
tar czf acme-backup.tar.gz -C data/firms acme
```

To restore:

```bash
tar xzf acme-backup.tar.gz -C data/firms
```

The Chroma persistent store + the BM25 pickle + the indexed-files
manifest together are sufficient to fully restore a firm's index on
any machine running the same firm-bot version.
