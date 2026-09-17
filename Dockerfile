# firm-bot container image.
#
# Build:
#     docker build -t firm-bot:latest .
#
# Run (mount your data dir so firms persist on the host):
#     docker run --rm -p 7860:7860 \
#         -v $(pwd)/data:/app/data \
#         -e FIRM_BOT_OLLAMA_HOST=http://host.docker.internal:11434 \
#         firm-bot:latest
#
# Notes:
# - The image uses python:3.12-slim. firm-bot supports 3.11+.
# - OCR needs tesseract + poppler. Both are installed below.
# - Mounting /app/data is what makes a firm's documents persist across
#   container rebuilds. Without it, every `docker run` is a fresh state.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# OCR + PDF deps.
# tesseract-ocr is the engine; tesseract-ocr-eng pulls the English language pack.
# poppler-utils provides pdftoppm, which pdf2image shells out to.
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        poppler-utils \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in a separate layer so re-builds are fast.
COPY pyproject.toml README.md ./
COPY firm_bot ./firm_bot
COPY eval ./eval

RUN pip install --upgrade pip && pip install .

# Default data dir lives inside the container; mount a volume to persist.
ENV FIRM_BOT_DATA_DIR=/app/data
RUN mkdir -p /app/data

EXPOSE 7860

# Healthcheck hits the FastAPI /healthz endpoint.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7860/healthz || exit 1

# Run uvicorn directly so signals (SIGTERM) are handled cleanly.
CMD ["uvicorn", "firm_bot.api:app", "--host", "0.0.0.0", "--port", "7860"]