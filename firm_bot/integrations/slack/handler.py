"""Slack event handler — translate a Slack message event into firm-bot.

The handler is intentionally narrow:

- Filter out events the bot should ignore (bot messages, edits, deletes,
  channel joins, etc.).
- Strip a leading bot mention if present (Slack sends ``<@U0LAN0Z89>``
  prefixed text on app_mention events).
- Call firm-bot via :class:`FirmBotClient`.
- Run :func:`format_answer` over the result.
- Return a list of message dicts ready to post back.

This module does **not** touch Slack's HTTP API. Operators wire it
into Slack's official runtime (Bolt for Python) and use the SDK's
``chat.postMessage`` to send each returned dict.

Firm mapping: this handler requires ``event["firm_slug"]`` to be set
by the wiring layer. The wiring layer is the right place to resolve
``channel → firm`` (channel-to-firm config, per-DM mapping, slash
command argument, etc.). If the field is missing we return a single
error message rather than guessing.
"""

from __future__ import annotations

import logging
from typing import Any

from .bot import FirmBotClient, FirmBotClientError
from .format import format_answer, strip_bot_mention

log = logging.getLogger("firm_bot.integrations.slack.handler")

#: Subtypes that mean "this is not a fresh user message".
#: ``message_changed`` and ``message_deleted`` are edit/delete events;
#: ``channel_join``/``channel_leave``/``thread_broadcast`` etc. have
#: their own semantics. We err on the side of skipping anything with a
#: ``subtype`` set — the wiring layer can override by stripping the
#: field before calling.
_IGNORED_SUBTYPES = frozenset(
    {
        "bot_message",
        "message_changed",
        "message_deleted",
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
        "channel_name",
        "channel_archive",
        "channel_unarchive",
        "pinned_item",
        "unpinned_item",
    }
)


def handle_message(
    event: dict[str, Any],
    client: FirmBotClient,
) -> list[dict[str, Any]]:
    """Process one Slack ``message`` / ``app_mention`` event.

    Parameters
    ----------
    event:
        Slack event payload. Must contain ``text`` (the message body,
        with leading ``<@U…>`` bot mention still present if any) and
        ``firm_slug`` (set by the wiring layer's channel-to-firm
        resolver). Other common fields (``channel``, ``user``, ``ts``,
        ``thread_ts``, ``bot_id``, ``subtype``) are honoured if
        present.
    client:
        Configured :class:`FirmBotClient` for the firm-bot API.

    Returns
    -------
    list[dict]
        Zero or more message dicts ready for Slack's
        ``chat.postMessage``. Each dict has ``text`` and ``blocks``
        keys. Empty list when the event is ignored.

    Notes
    -----
    Errors from firm-bot are caught and converted into a single
    user-visible error message — never raised to the caller. Slack's
    Events API requires a 200 response within 3 seconds; surfacing
    a single error string keeps us inside that window while still
    telling the user what went wrong.
    """
    text = _extract_question(event)
    if text is None:
        return []
    firm_slug = _extract_firm_slug(event)
    if firm_slug is None:
        return [_missing_firm_message(event)]
    return _query_and_format(event, client, firm_slug, text)


def _extract_question(event: dict[str, Any]) -> str | None:
    """Return the question text from ``event``, or ``None`` to skip."""
    if not event:
        return None
    if event.get("bot_id"):
        # Slack sets bot_id on messages from apps and bots, including
        # our own replies. Avoid feedback loops.
        return None
    subtype = event.get("subtype")
    if isinstance(subtype, str) and subtype in _IGNORED_SUBTYPES:
        return None
    raw_text = event.get("text")
    if not isinstance(raw_text, str):
        return None
    text = strip_bot_mention(raw_text).strip()
    return text or None


def _extract_firm_slug(event: dict[str, Any]) -> str | None:
    """Return the firm slug from ``event``, or ``None`` when not wired."""
    firm_slug = event.get("firm_slug")
    if isinstance(firm_slug, str) and firm_slug:
        return firm_slug
    return None


def _query_and_format(
    event: dict[str, Any],
    client: FirmBotClient,
    firm_slug: str,
    text: str,
) -> list[dict[str, Any]]:
    """Query firm-bot and format the answer."""
    history = event.get("history")  # optional; wiring layer may inject it
    try:
        result = client.query(firm_slug, text, history=history)
    except FirmBotClientError as exc:
        log.warning(
            "slack.handle_message: firm-bot error firm=%s status=%s: %s",
            firm_slug,
            exc.status_code,
            exc,
        )
        return [_error_message(f"firm-bot error ({exc.status_code or 'network'})")]

    answer = result.get("answer", "") if isinstance(result, dict) else ""
    cited_raw = result.get("cited") if isinstance(result, dict) else None
    cited: list[str] = list(cited_raw) if isinstance(cited_raw, list) else []

    url_map_raw = event.get("url_map")
    url_map: dict[str, str] | None = url_map_raw if isinstance(url_map_raw, dict) else None
    header_raw = event.get("header")
    header = header_raw if isinstance(header_raw, str) else None

    payload = format_answer(
        answer or "(no answer returned)",
        cited,
        url_map=url_map,
        header=header,
    )
    messages: list[dict[str, Any]] = list(payload["messages"])
    return messages


def _missing_firm_message(event: dict[str, Any]) -> dict[str, Any]:
    log.warning(
        "slack.handle_message: missing firm_slug (channel=%s user=%s)",
        event.get("channel"),
        event.get("user"),
    )
    text = (
        ":warning: firm-bot: no firm is configured for this channel. "
        "Set up a channel-to-firm mapping in your Slack adapter wiring."
    )
    return _error_message(text)


def _error_message(text: str) -> dict[str, Any]:
    """Build a single-message error payload."""
    prefixed = f":warning: {text}"
    return {
        "text": prefixed,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": prefixed},
            }
        ],
    }
