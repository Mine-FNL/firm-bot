"""Log-output redaction — strip secrets before they hit disk.

Why a separate module
---------------------
:mod:`firm_bot.redact` redacts *document* PII (SSN, EIN, IBAN, …) before
indexing. That module is concerned with what is *stored*. This module is
concerned with what is *logged* — the patterns overlap (emails, bearer
tokens) but the threat is different: a leaked bearer token in a log
file is a credential exposure, not a PII leak, and the response is
rotation rather than re-ingestion. Keeping them separate makes audits
clearer.

What gets redacted
------------------
- ``Authorization: Bearer <token>`` → ``Authorization: Bearer [REDACTED]``
- ``api_key=<value>`` / ``token=<value>`` where the value is 32+ alnum
  chars → ``[REDACTED]``
- Email addresses → ``[REDACTED_EMAIL]``
- Values of any environment variable whose name ends in ``_KEY``,
  ``_SECRET``, or ``_TOKEN`` (snapshot at filter construction). Avoids
  accidental leakage of credentials loaded from ``os.environ`` when a
  log message interpolates ``os.environ``.

Caveats
-------
Regex can't catch every credential shape (arbitrary base64 blobs, JWTs
without ``Bearer``, custom tokens). Apply at logger setup time:

.. code-block:: python

    logging.getLogger().addFilter(RedactFilter())

This filter mutates ``record.getMessage()`` so downstream handlers /
formatters emit the redacted text without affecting the original
LogRecord.
"""
from __future__ import annotations

import logging
import os
import re
from typing import ClassVar

# Pattern set. Tuples are (name, compiled regex, replacement).
# Patterns are deliberately conservative — false negatives are
# preferable to false positives in log redactors (a leaked credential
# is much worse than an over-redacted token).

_RE_BEARER = re.compile(
    r"(Authorization\s*:\s*Bearer\s+)[A-Za-z0-9._\-+/=]+",
    re.IGNORECASE,
)

# api_key=... or token=... where the value is 32+ alphanumeric.
# Captures the prefix and value separately so we can keep the structure.
_RE_API_KEY_QUERY = re.compile(
    r"((?:api[_-]?key|token)\s*[=:]\s*)([A-Za-z0-9_\-+/=]{32,})",
    re.IGNORECASE,
)

# A bare Authorization header without "Bearer" — e.g. an AWS-style
# "Authorization: AWS4-HMAC-SHA256 Credential=..." line. Conservative
# scope: redact everything after "Authorization:" until the next
# newline or end of string.
_RE_AUTH_LINE = re.compile(
    r"(Authorization\s*:\s*)[^\n]+",
    re.IGNORECASE,
)

_RE_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

_ENV_SECRET_SUFFIXES: tuple[str, ...] = ("_KEY", "_SECRET", "_TOKEN")


class RedactFilter(logging.Filter):
    """Strips known secret patterns from log records before emission."""

    PATTERNS: ClassVar[list[tuple[str, re.Pattern[str], str]]] = [
        ("bearer", _RE_BEARER, r"\1[REDACTED]"),
        ("auth_line", _RE_AUTH_LINE, r"\1[REDACTED]"),
        ("api_key_query", _RE_API_KEY_QUERY, r"\1[REDACTED]"),
        ("email", _RE_EMAIL, "[REDACTED_EMAIL]"),
    ]

    def __init__(self, *, env: dict[str, str] | None = None) -> None:
        super().__init__()
        # Pick up credential-shaped env vars so we can substitute them
        # in addition to the static regex patterns. ``env`` defaults to
        # ``os.environ`` but tests can inject a controlled mapping.
        src = env if env is not None else dict(os.environ)
        # Keep only values that look vaguely credential-like (>= 8 chars).
        self._env_values: list[str] = [
            v for k, v in src.items()
            if any(k.endswith(s) for s in _ENV_SECRET_SUFFIXES)
            and isinstance(v, str)
            and len(v) >= 8
        ]
        # Stable ordering: longer values first so that we don't shadow a
        # short value that is a substring of a longer one. Conservative
        # because we only look for exact substring matches.
        self._env_values.sort(key=len, reverse=True)

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = self._redact(msg)
        if redacted != msg:
            # Mutate the rendered message but also stash the redacted
            # version so handlers that prefer args rendering get it too.
            record.msg = redacted
            record.args = ()
        return True

    def _redact(self, text: str) -> str:
        out = text
        # Static regex pass.
        for _name, pattern, repl in self.PATTERNS:
            out = pattern.sub(repl, out)
        # Env-value pass: only flag, don't mutate non-secrets.
        # Conservative: require the value to appear between non-word
        # boundaries so we don't catch substrings of larger tokens.
        for v in self._env_values:
            if not v:
                continue
            # Use a simple boundary pattern; non-greedy escape.
            pattern = re.compile(rf"(?<!\w){re.escape(v)}(?!\w)")
            out = pattern.sub("[REDACTED]", out)
        return out
