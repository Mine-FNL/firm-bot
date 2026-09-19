"""Slack workspace adapter for firm-bot.

This adapter lets a workspace's Slack users ask firm-bot questions from
Slack (channel mention, DM, slash command) and get the cited answer
back as a threaded reply.

Design choices:

- **Pure stdlib.** No dependency on ``slack-sdk`` / ``slack-bolt``.
  Operators wire these primitives into the Slack runtime of their
  choice (Bolt for Python, a custom aiohttp handler, etc.).
- **Signing-secret verification** is the only thing the adapter
  consumes the raw HTTP request for — see :func:`verify_slack_signature`.
- **HTTP to firm-bot** uses :mod:`urllib.request` so we don't pull in
  ``httpx`` / ``requests`` for the adapter surface.
- **No server in this package.** The wiring layer instantiates
  :class:`FirmBotClient` and routes Slack events to
  :func:`handle_message`.
"""

from __future__ import annotations

from .bot import FirmBotClient, FirmBotClientError
from .format import format_answer
from .handler import handle_message
from .verify import verify_slack_signature

__all__ = [
    "FirmBotClient",
    "FirmBotClientError",
    "format_answer",
    "handle_message",
    "verify_slack_signature",
]
