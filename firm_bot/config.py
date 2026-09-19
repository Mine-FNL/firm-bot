"""Configuration for firm-bot — root + per-firm dataclasses.

Resolution order
----------------

1. Defaults baked into the dataclass.
2. Environment variables (``FIRM_BOT_*``) override defaults.
3. ``<data_dir>/config.yaml`` overrides env. The data_dir itself is
   sourced from the env var first (``FIRM_BOT_DATA_DIR``), then from
   ``--data-dir`` on the CLI, then defaults to ``./data``.

Firm config validation
--------------------

``FirmConfig.validate()`` checks that slug, name, llm_model (if set),
and system_prompt (if set) are usable. Failures raise ``ConfigError``
so the operator gets a clear message instead of a stack trace later
in the ingest pipeline.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError, InvalidSlugError

log = logging.getLogger("firm_bot.config")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_RE.match(slug))


@dataclass
class RootConfig:
    """Global settings shared across firms."""

    data_dir: str = "./data"
    ollama_host: str = "http://127.0.0.1:11434"
    embedding_backend: str = "sentence-transformers"  # or "fastembed"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    llm_model: str = "qwen2.5-coder:14b"          # answer model
    llm_judge_model: str = "qwen2.5-coder:7b"    # guard / eval judge
    llm_timeout_s: float = 120.0
    chunk_size: int = 1200                        # characters per chunk
    chunk_overlap: int = 200                      # 16% overlap
    min_chunk_size: int = 120
    hybrid_bm25_weight: float = 0.45
    hybrid_dense_weight: float = 0.55
    retrieve_k: int = 12                          # candidates before re-rank
    answer_k: int = 6                             # chunks fed to answer LLM
    # Cross-encoder reranker (v0.2 preview). Empty disables reranking.
    # Set to "cross-encoder/ms-marco-MiniLM-L-6-v2" to enable.
    reranker_model: str = ""
    rerank_top_k: int = 12                        # how many candidates to re-rank
    incremental_indexing: bool = True             # skip files whose hash hasn't changed
    max_upload_bytes: int = 200 * 1024 * 1024     # 200 MB (hard cap on uploads)
    # ---- security hardening ----
    # See firm_bot/security/* for the matching implementation.
    # Defaults are deliberately conservative for a single-tenant firm.
    rate_limit_rps: float = 10.0                  # per-IP requests/sec sustained
    rate_limit_burst: int = 20                    # per-IP burst tokens
    body_max_bytes: int = 1 * 1024 * 1024         # 1 MB — general request body cap
    # CORS allow-list. Empty list = no CORS headers emitted (fail closed).
    # Pass ["*"] to allow any origin (development only).
    cors_allow_origins: list[str] = field(default_factory=list)
    # ---- API key auth (default-on) ----
    # As of v0.2 the API key gate is **enabled by default**. If
    # ``require_api_key`` is True and ``api_keys`` is empty at startup,
    # :meth:`ensure_api_key` generates a fresh 256-bit URL-safe token,
    # prints it once with a ``GENERATED_API_KEY`` marker, and persists
    # it to ``<data_dir>/config.yaml`` so subsequent boots don't
    # rotate. Set ``FIRM_BOT_REQUIRE_API_KEY=0`` to disable entirely.
    #
    # For multi-worker deployments (``uvicorn --workers N``) auto-gen
    # is unsafe — every worker would race to generate and persist a
    # different key, breaking the others. Set ``FIRM_BOT_API_KEYS=<k>``
    # in that case. UI / health / metrics are always exempt.
    require_api_key: bool = True
    api_keys: list[str] = field(default_factory=list)
    # ---- audit log ----
    # Retention window for the per-firm query audit log. Records older
    # than this are pruned on read. Set to 0 to disable pruning
    # (records retained indefinitely). Compliance reviews typically
    # ask for 90 days; the WHITEPAPER recommends the same.
    audit_retention_days: int = 90
    # Path inside the firm directory for the audit log file.
    # Default ``audit-log.jsonl``; change only if you have a strong
    # reason (custom SIEM ingest, etc).
    audit_log_filename: str = "audit-log.jsonl"
    log_level: str = "INFO"

    # ---- factories ----

    @classmethod
    def from_env(cls, data_dir: str | None = None) -> RootConfig:
        """Build a RootConfig from env vars and the YAML file under data_dir."""
        dd = (
            data_dir
            or os.environ.get("FIRM_BOT_DATA_DIR")
            or "./data"
        )
        cfg_path = Path(dd) / "config.yaml"
        if cfg_path.exists():
            cfg = cls.load(cfg_path)
            cfg.data_dir = dd
        else:
            cfg = cls(data_dir=dd)
        # env overrides on top of YAML (env wins)
        for key in (
            "ollama_host",
            "embedding_model",
            "llm_model",
            "llm_judge_model",
            "chunk_size",
            "chunk_overlap",
            "hybrid_bm25_weight",
            "hybrid_dense_weight",
            "retrieve_k",
            "answer_k",
            "rate_limit_rps",
            "rate_limit_burst",
            "max_upload_bytes",
            "body_max_bytes",
            "audit_retention_days",
            "audit_log_filename",
            "log_level",
            "require_api_key",
        ):
            env_key = f"FIRM_BOT_{key.upper()}"
            val = os.environ.get(env_key)
            if val is None:
                continue
            current = getattr(cfg, key)
            if isinstance(current, bool):
                coerced: Any = val.lower() in {"1", "true", "yes"}
            elif isinstance(current, int):
                coerced = int(val)
            elif isinstance(current, float):
                coerced = float(val)
            else:
                coerced = val
            setattr(cfg, key, coerced)

        # List-type env overrides. Comma-separated: ORIGIN=a,b,c → ['a','b','c'].
        csv_key_map = {
            "cors_allow_origins": "FIRM_BOT_CORS_ALLOW_ORIGINS",
            "api_keys": "FIRM_BOT_API_KEYS",
        }
        for field_name, env_key in csv_key_map.items():
            val = os.environ.get(env_key)
            if val is None:
                continue
            items = [s.strip() for s in val.split(",") if s.strip()]
            setattr(cfg, field_name, items)
        cfg.validate()
        return cfg

    @classmethod
    def load(cls, path: Path) -> RootConfig:
        raw = yaml.safe_load(path.read_text()) or {}
        raw.setdefault("data_dir", str(path.parent.resolve()))
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(asdict(self), sort_keys=True))

    # ---- validation ----

    def validate(self) -> None:
        if not self.data_dir:
            raise ConfigError("data_dir must be set", user_message="data_dir must be set.")
        if not self.ollama_host.startswith(("http://", "https://")):
            raise ConfigError(
                f"ollama_host must be http(s)://, got {self.ollama_host!r}",
                user_message="Ollama host must start with http:// or https://.",
            )
        if self.chunk_size < 200:
            raise ConfigError("chunk_size must be >= 200", user_message="chunk_size must be at least 200 characters.")
        if self.chunk_overlap >= self.chunk_size:
            raise ConfigError(
                "chunk_overlap must be < chunk_size",
                user_message="Chunk overlap must be smaller than chunk size.",
            )
        if not (0 <= self.hybrid_bm25_weight <= 1) or not (0 <= self.hybrid_dense_weight <= 1):
            raise ConfigError(
                "hybrid weights must be in [0, 1]",
                user_message="Hybrid weights must be between 0 and 1.",
            )
        if self.retrieve_k < 1 or self.answer_k < 1:
            raise ConfigError(
                "retrieve_k and answer_k must be >= 1",
                user_message="retrieve_k and answer_k must be at least 1.",
            )
        if self.rate_limit_rps <= 0:
            raise ConfigError(
                "rate_limit_rps must be > 0",
                user_message="Rate limit (requests/sec) must be positive.",
            )
        if self.rate_limit_burst < 1:
            raise ConfigError(
                "rate_limit_burst must be >= 1",
                user_message="Rate limit burst must be at least 1.",
            )
        if self.body_max_bytes < 1024:
            raise ConfigError(
                "body_max_bytes must be >= 1024",
                user_message="Body size cap must be at least 1024 bytes.",
            )

    # ---- API key management ----

    def ensure_api_key(self) -> None:
        """Generate + persist an API key if none is configured.

        Behaviour:
          - No-op when ``require_api_key`` is False.
          - No-op when ``api_keys`` already has at least one entry.
          - Otherwise: generate a 256-bit URL-safe token, append it
            to ``api_keys``, log it ONCE with a ``GENERATED_API_KEY``
            marker (the operator MUST save it — we never log it again),
            and persist to ``<data_dir>/config.yaml``.

        Safety: only safe for single-worker deployments. Multi-worker
        setups (``uvicorn --workers N``) race on the YAML write — set
        ``FIRM_BOT_API_KEYS=<key>`` explicitly to avoid the race.
        """
        if not self.require_api_key:
            return
        if self.api_keys:
            return
        key = secrets.token_urlsafe(32)  # 256 bits
        self.api_keys = [key]
        # Loud, banner-style warning. The operator needs to see this
        # in their boot logs and capture it before it scrolls off.
        log.warning("=" * 72)
        log.warning("GENERATED_API_KEY (save this — it will NOT be shown again):")
        log.warning("  Authorization: Bearer %s", key)
        log.warning(
            "Or set FIRM_BOT_API_KEYS=<key> in your environment for "
            "multi-worker / container deployments."
        )
        log.warning("=" * 72)
        # Persist so a restart doesn't rotate the key. Best-effort —
        # a write failure shouldn't break the process; the warning
        # above already told the operator to copy it.
        try:
            cfg_path = Path(self.data_dir) / "config.yaml"
            self.save(cfg_path)
            log.info("persisted generated api key to %s", cfg_path)
        except Exception as e:  # pragma: no cover - defensive
            log.warning("could not persist generated api key: %s", e)


@dataclass
class FirmConfig:
    """Per-tenant settings."""

    slug: str
    name: str
    system_prompt: str = ""
    llm_model: str = ""                           # empty → fall back to root
    contact_email: str = ""
    notes: str = ""
    # PII categories to redact at ingest time. None = redact everything
    # firm_bot.redact.DEFAULT_CATEGORIES knows about. Pass an empty list
    # to disable redaction for this firm.
    redact_categories: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, firm_dir: Path) -> FirmConfig:
        path = firm_dir / "config.yaml"
        if not path.exists():
            return cls(slug=firm_dir.name, name=firm_dir.name.replace("-", " ").title())
        raw = yaml.safe_load(path.read_text()) or {}
        raw["slug"] = firm_dir.name
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})

    def save(self, firm_dir: Path) -> None:
        path = firm_dir / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(asdict(self), sort_keys=True))

    def validate(self) -> None:
        if not is_valid_slug(self.slug):
            raise InvalidSlugError(f"invalid slug: {self.slug!r}")
        if not self.name.strip():
            raise ConfigError("name is required", user_message="Firm name is required.")
        if self.contact_email and "@" not in self.contact_email:
            log.warning("contact_email %r does not look like an email", self.contact_email)

    def effective_system_prompt(self, root: RootConfig) -> str:
        """Compose the prompt that primes every chat call for this firm."""
        base = (
            "You are a careful assistant for a professional services firm. "
            "Answer ONLY using the provided source chunks. "
            "Cite every factual claim with the bracketed source marker exactly "
            "as shown in the context, e.g. [contract.pdf:p.4]. "
            "If the sources do not contain the answer, say so plainly — "
            "do not guess. Prefer short, direct sentences; the operator "
            "reading your output is a busy human."
        )
        if self.system_prompt:
            return f"{base}\n\nFirm-specific instructions:\n{self.system_prompt}"
        return base
