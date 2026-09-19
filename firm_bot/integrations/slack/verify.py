"""Slack signing-secret verification.

Slack signs every inbound Events API / interactivity payload with
``v0=<HMAC-SHA256(signing_secret, "v0:{ts}:{body}")>`` and sends the
result in ``X-Slack-Signature``. We verify it per Slack's documented
algorithm: https://api.slack.com/authentication/verifying-requests-from-slack

The version prefix is pinned to ``v0`` — if Slack ships ``v1`` later,
we want a hard rejection rather than silent acceptance.

Key points:

- Timestamp must be within ``MAX_TIMESTAMP_AGE_S`` (300 s, per spec).
- Body must be the raw HTTP body bytes — Slack signs the bytes exactly
  as received, so a re-encoded JSON body will not validate.
- Comparison is constant-time to avoid timing leaks.
"""

from __future__ import annotations

import hashlib
import hmac
import time

#: Maximum allowed age of the ``X-Slack-Request-Timestamp`` header.
#: Slack's spec is 5 minutes (300 s); we keep the exact value.
MAX_TIMESTAMP_AGE_S: int = 300

#: Pinned Slack signature version. Slack currently signs with ``v0``;
#: ``v1`` exists for some newer flows but isn't sent on the Events API.
SLACK_SIGNATURE_VERSION: str = "v0"


def verify_slack_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    signing_secret: str,
    *,
    now_s: float | None = None,
) -> bool:
    """Return ``True`` iff ``signature`` is a valid Slack signature for ``body``.

    Parameters
    ----------
    body:
        Raw HTTP request body (bytes). Must be the exact bytes Slack
        signed — do not re-encode a parsed dict back to JSON.
    timestamp:
        Value of the ``X-Slack-Request-Timestamp`` header (string of
        integer seconds since epoch).
    signature:
        Value of the ``X-Slack-Signature`` header, including the
        ``v0=`` prefix.
    signing_secret:
        The app's signing secret (matches the one configured in the
        Slack app's "Basic Information" page).
    now_s:
        Optional override of "now" for deterministic tests. When
        ``None`` we use :func:`time.time`.

    Returns
    -------
    bool
        ``True`` only if the timestamp is fresh, the version prefix
        matches ``v0``, and the HMAC matches.

    Notes
    -----
    The function is intentionally total — never raises on malformed
    input, just returns ``False``. That matches the "fail closed"
    expectation of a webhook gate: the caller decides whether to
    respond 401, 403, or log + drop.
    """
    if not body or not timestamp or not signature or not signing_secret:
        return False

    # Version prefix check — must be exactly "v0=".
    prefix = f"{SLACK_SIGNATURE_VERSION}="
    if not signature.startswith(prefix):
        return False

    # Timestamp freshness check.
    try:
        ts_int = int(timestamp)
    except (TypeError, ValueError):
        return False
    reference_now = int(now_s) if now_s is not None else int(time.time())
    if abs(reference_now - ts_int) > MAX_TIMESTAMP_AGE_S:
        return False

    # HMAC-SHA256 over "v0:{timestamp}:{body}".
    mac = hmac.new(
        signing_secret.encode("utf-8"),
        f"{SLACK_SIGNATURE_VERSION}:{timestamp}:".encode() + body,
        hashlib.sha256,
    )
    expected = prefix + mac.hexdigest()

    # Constant-time compare. ``hmac.compare_digest`` requires equal-length
    # strings; pad-free path is fine because we already length-checked
    # implicitly via the hexdigest format.
    return hmac.compare_digest(expected, signature)
