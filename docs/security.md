# Security

## Threat model

firm-bot is designed to be deployed inside a firm's network where the
operator already trusts the host. The threat model assumes:

- The host running firm-bot is trusted (controlled by the firm).
- Local Ollama is trusted.
- Anyone who can reach the firm-bot HTTP endpoint is trusted.

If you expose firm-bot to the public internet, additional measures
(firewall, reverse-proxy auth, rate limiting) are your responsibility
and out of scope for v0.1 — see "Hardening for public deployment"
in [Deployment](deployment.md).

## What firm-bot does to keep data private

- **Local Ollama, no cloud.** No telemetry, no remote calls. The
  only outbound traffic is to the configured `ollama_host`.
- **Embedding model downloads.** `sentence-transformers/all-MiniLM-L6-v2`
  is fetched from Hugging Face on first run (~80 MB). To run fully
  offline, pre-download the model and set `HF_HUB_OFFLINE=1`.
- **No auth.** v0.1 assumes closed deployment. Do not expose to the
  internet without adding auth.
- **Per-firm isolation.** Each firm's chunks live in their own
  Chroma collection and BM25 pickle under
  `<data_dir>/firms/<slug>/store/`. The slug is the only join key —
  there is no shared index across firms.

## PII redaction at ingest

The optional `redact_categories` field on `FirmConfig` enables
regex-based redaction before chunks are made. Supported categories:
`ssn`, `ein`, `email`, `phone`, `credit_card`, `iban`, `ipv4`.
Matches are replaced with stable category tokens (`[SSN-REDACTED]`)
so the operator can still see *that* a number was there without
seeing *which* one. See [Configuration](configuration.md).

Regex is not a substitute for proper NER; we catch common formats
but miss names, addresses, and unusual identifiers. For high-stakes
deployments, layer a real NER model (presidio, GLiNER) on top.

## What firm-bot does NOT do

- **No encryption at rest.** Chunks and indexes live on the host's
  filesystem. If the host is compromised, the documents are readable.
  For encrypted storage, run firm-bot on an encrypted volume (FileVault,
  LUKS).
- **No access logging.** v0.1 logs ingestion and query failures but
  does not log every question asked. If your firm needs a query audit
  log, file an issue and we will add it.
- **No model-side isolation.** Multiple firms may share an Ollama
  instance. If you need per-firm model isolation, run one Ollama
  instance per firm on a separate port.

## Reporting a vulnerability

Email `security@firm-bot.dev` (placeholder — update before
publishing). Please do not file a public issue for vulnerabilities
that affect document confidentiality.

For non-security bugs, please use the standard GitHub issue template.

## Audit checklist for compliance teams

If you're evaluating firm-bot for a regulated deployment, here's
what to verify in your pilot:

| Check                              | Where to verify                                     |
|------------------------------------|-----------------------------------------------------|
| No outbound traffic except Ollama | Network monitor while running                        |
| Per-firm data isolation            | `data/firms/<slug>/` is the only data path           |
| PII redaction active               | `redact_categories` in `config.yaml`                |
| OCR for scanned PDFs               | Tesseract + poppler-utils installed; OCR cap set    |
| Audit log of questions             | Not yet shipped; track via reverse-proxy access logs |
| Encryption at rest                 | Run on encrypted volume                             |
| Access control                     | Reverse-proxy auth + rate limits                    |
| Backup strategy                    | `tar czf` per-firm; restore to a fresh host         |
