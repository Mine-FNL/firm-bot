"""Email ingestion for firm-bot.

Handles:
- ``.eml`` — a single RFC 822 message
- ``.mbox`` — a Unix mailbox (many messages, separated by ``From `` lines)

Each message becomes one ``Document`` whose metadata carries sender,
recipient(s), subject, date, and message-id. The text is composed as
``Subject: ...\\nFrom: ...\\nTo: ...\\nDate: ...\\n\\n<body>`` so a
retriever query like "what did Alice say about the audit on March 5"
can match against the headers without us shipping a custom email-aware
embedder.

We deliberately do NOT thread unrolling in v0.1. Lawyers ask
"show me everything Alice said about the audit"; a thread-collapse pass
would actually hurt retrieval. Document-level granularity is correct.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import logging
import mailbox
from email.message import Message
from pathlib import Path

from .common import Document, stable_doc_id

log = logging.getLogger("firm_bot.ingest.eml")


def _msg_to_document(path: Path, msg: Message) -> Document:
    """Turn one email Message into a Document.

    Quoted-printable / base64 / etc. are decoded by ``email.policy.default``.
    The ``email`` package's stubs are incomplete for ``Message``; we use
    ``getattr`` to stay safe under mypy --strict.
    """

    def get(key: str, default: str = "") -> str:
        v = msg.get(key, default) or default
        return str(v)

    subject = get("Subject")
    from_ = get("From")
    to = get("To")
    cc = get("Cc")
    date = get("Date")
    msg_id = get("Message-ID") or "(no-id)"

    body_text = ""
    get_body = getattr(msg, "get_body", None)
    if get_body is not None:
        try:
            body = get_body(preferencelist=("plain", "html"))
            if body is not None:
                get_content = getattr(body, "get_content", None)
                if get_content is not None:
                    body_text = str(get_content() or "")
        except (LookupError, ValueError, AttributeError):
            body_text = _walk_parts(msg)
    if not body_text:
        body_text = _walk_parts(msg)

    header_block = (
        f"Subject: {subject}\n"
        f"From: {from_}\n"
        f"To: {to}\n" + (f"Cc: {cc}\n" if cc else "") + f"Date: {date}\n"
        f"Message-ID: {msg_id}\n\n"
    )
    text = header_block + body_text
    return Document(
        doc_id=stable_doc_id(str(path), msg_id),
        text=text,
        metadata={
            "source_path": str(path),
            "source_name": path.name,
            "subject": subject,
            "from": from_,
            "to": to,
            "cc": cc,
            "date": date,
            "message_id": msg_id,
            "extractor": "eml",
        },
    )


def _walk_parts(msg: Message) -> str:
    """Extract text from a multipart message; prefer plain over html."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                get_content = getattr(part, "get_content", None)
                if get_content is not None:
                    try:
                        return str(get_content() or "")
                    except Exception:
                        continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                get_content = getattr(part, "get_content", None)
                if get_content is not None:
                    try:
                        return _strip_html(str(get_content() or ""))
                    except Exception:
                        continue
    get_content = getattr(msg, "get_content", None)
    if get_content is not None:
        try:
            return str(get_content() or "")
        except Exception:
            return ""
    return ""


def _strip_html(html: str) -> str:
    """Cheap HTML → text for emails that only ship an HTML part."""
    import re

    html = re.sub(r"<style\b[^>]*>.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    html = re.sub(r"</p>", "\n\n", html, flags=re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    import html as html_lib

    return html_lib.unescape(html)


def extract_eml(path: Path) -> list[Document]:
    """Parse one .eml file into one Document."""
    try:
        raw = path.read_bytes()
        msg = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception as e:
        log.warning("eml parse failed %s: %s", path, e)
        return []
    return [_msg_to_document(path, msg)]


def extract_mbox(path: Path) -> list[Document]:
    """Parse a Unix mbox file into one Document per message."""
    out: list[Document] = []
    try:
        mbox = mailbox.mbox(str(path))
    except Exception as e:
        log.warning("mbox open failed %s: %s", path, e)
        return out
    for i, msg in enumerate(mbox):
        try:
            out.append(_msg_to_document(path, msg))
        except Exception as e:
            log.warning("mbox message %d of %s failed: %s", i, path, e)
    return out
