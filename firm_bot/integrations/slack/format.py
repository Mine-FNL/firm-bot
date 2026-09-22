"""Convert firm-bot answers into Slack-ready message payloads.

Slack has two parallel surfaces:

- **mrkdwn** — the inline-format dialect used in ``text`` fields
  (``*bold*``, ``_italic_``, ``<url|label>``, ``~strike~``, backtick-code).
  Crucially it is **not** CommonMark: asterisks mean bold and you
  cannot use ``**word**`` for bold.
- **Block Kit** — structured JSON ``blocks`` array (``section``,
  ``context``, ``actions``, …) for richer cards.

This module produces both: ``text`` for the simple chat.postMessage
path, ``blocks`` for the rich path. The caller picks one — they
post the same content.

Citation markers from firm-bot look like ``[contract.pdf:p.4]`` or
``[nda.docx§2]``. Slack mrkdwn cannot render raw square brackets as
link labels, so we rewrite them into Slack's ``<url|label>`` form
when the caller provides a URL mapping, or ``*bold*`` otherwise.

Slack's hard limit is 4000 chars per message (block-kit section text
is 3000 — we use the safer 3000 cap so a single section block never
truncates).
"""

from __future__ import annotations

import re
from typing import Any

#: Max chars per Slack message. Slack's hard limit is 4000, but block-kit
#: ``section.text`` is capped at 3000. We use 3000 so a single ``section``
#: block never has to be split across blocks.
SLACK_MESSAGE_LIMIT: int = 3000

#: Citation marker regex — matches ``[...]`` blocks, the same shape
#: firm-bot's :func:`firm_bot.answer.prompt.extract_cited_sources` uses.
_CITATION_RE = re.compile(r"\[([^\]\[\n]+)\]")

#: Slack mention regex — strips leading ``<@USERID>`` bot mention.
_MENTION_RE = re.compile(r"^\s*<@[A-Z0-9]+>\s*")


def format_answer(
    answer: str,
    cited: list[str] | None = None,
    *,
    url_map: dict[str, str] | None = None,
    header: str | None = None,
) -> dict[str, Any]:
    """Convert a firm-bot answer + cited markers into Slack message(s).

    Parameters
    ----------
    answer:
        Raw answer text from firm-bot. May contain ``[file.pdf:p.4]``
        citation markers and Slack-incompatible characters (``<``,
        ``>``, ``&``).
    cited:
        Optional list of citation marker strings the LLM actually
        cited (as returned by ``extract_cited_sources``). These are
        rendered as a ``Sources: …`` footer. Order is preserved.
    url_map:
        Optional ``marker → URL`` mapping. When a citation marker has
        an entry, it becomes a clickable Slack ``<url|label>`` link;
        otherwise it renders as bold text.
    header:
        Optional bold header line (e.g. the firm name) prepended to
        the answer.

    Returns
    -------
    dict[str, Any]
        ``{"messages": [{"text": ..., "blocks": [...]}, ...],
           "cited": [...]}``

        ``messages`` contains one or more message payloads. Each has a
        ``text`` field (full mrkdwn string for the simple chat path)
        and a ``blocks`` field (Block Kit JSON for the rich path).
        Long answers are split at paragraph boundaries; the
        ``Sources:`` footer rides on the last message so the reader
        sees context + sources together.

    Notes
    -----
    We deliberately return a dict rather than a string: the caller
    can choose to post ``text`` directly, or pass ``blocks`` to a
    richer Slack SDK without having to re-parse anything.
    """
    cited = list(cited) if cited else []
    url_map = url_map or {}

    formatted_answer = _rewrite_citations(answer, url_map)

    chunks: list[str] = []
    if header:
        chunks.append(f"*{_escape_mrkdwn(header)}*")
    chunks.append(formatted_answer)

    sources_block = _format_sources(cited, url_map)
    if sources_block:
        chunks.append("")
        chunks.append(sources_block)

    full_text = "\n".join(chunks)
    parts = _split_text(full_text, SLACK_MESSAGE_LIMIT)

    messages: list[dict[str, Any]] = []
    for part in parts:
        messages.append(
            {
                "text": part,
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": part}},
                ],
            }
        )

    return {"messages": messages, "cited": cited}


def strip_bot_mention(text: str) -> str:
    """Strip a leading ``<@USERID>`` bot mention from a message.

    Slack sends app mentions as ``"<@U0LAN0Z89> what is the cap?"``;
    we want just the question text. Non-mentions are returned
    unchanged.
    """
    return _MENTION_RE.sub("", text, count=1)


def _rewrite_citations(text: str, url_map: dict[str, str]) -> str:
    """Replace each ``[marker]`` in ``text`` with a Slack link or bold."""

    def replace(match: re.Match[str]) -> str:
        marker = match.group(1).strip()
        url = url_map.get(marker)
        safe = _escape_mrkdwn(marker)
        if url:
            return f"<{url}|{safe}>"
        return f"*{safe}*"

    return _CITATION_RE.sub(replace, text)


def _format_sources(cited: list[str], url_map: dict[str, str]) -> str:
    """Build the ``*Sources:* …`` footer line.

    Returns an empty string when ``cited`` is empty.
    """
    if not cited:
        return ""
    parts: list[str] = []
    for marker in cited:
        url = url_map.get(marker)
        safe = _escape_mrkdwn(marker)
        if url:
            parts.append(f"<{url}|{safe}>")
        else:
            parts.append(f"*{safe}*")
    return "*Sources:* " + " · ".join(parts)


def _split_text(text: str, limit: int) -> list[str]:
    """Split ``text`` into chunks no longer than ``limit`` chars.

    Splitting prefers paragraph boundaries (``\\n\\n``), then line
    boundaries (``\\n``), then word boundaries. A long token with no
    whitespace is hard-cut at the limit.

    The cut discards the separator and trims surrounding whitespace
    on the next chunk so messages don't start with blank lines.
    """
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit)
        if cut == -1:
            cut = remaining.rfind("\n", 0, limit)
        if cut == -1:
            cut = remaining.rfind(" ", 0, limit)
        if cut <= 0:
            # No good break — hard cut. Leave a marker so the reader
            # knows this is a continuation.
            cut = limit
            part = remaining[:cut]
            next_remaining = remaining[cut:]
        else:
            part = remaining[:cut].rstrip()
            next_remaining = remaining[cut:].lstrip("\n")
        parts.append(part)
        remaining = next_remaining

    if remaining:
        parts.append(remaining)

    return parts


def _escape_mrkdwn(text: str) -> str:
    """Escape characters that would be interpreted as Slack mrkdwn.

    Slack mrkdwn treats ``&``, ``<``, and ``>`` specially (entities
    and link syntax). Escape them so a citation marker like
    ``Section <3.2>`` doesn't get parsed as a malformed link.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
