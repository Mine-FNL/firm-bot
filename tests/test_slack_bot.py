"""Tests for the firm_bot.integrations.slack adapter.

No real Slack API calls — we mock ``urllib.request.urlopen`` for the
HTTP client and exercise the verification / format / handler logic
against deterministic inputs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from unittest.mock import patch

import pytest

from firm_bot.integrations.slack import (
    FirmBotClient,
    FirmBotClientError,
    format_answer,
    handle_message,
    verify_slack_signature,
)
from firm_bot.integrations.slack.format import strip_bot_mention

# ============================================================================
# verify.py — signature verification
# ============================================================================


def _sign(body: bytes, timestamp: str, secret: str) -> str:
    """Compute a Slack v0 signature exactly the way Slack does it."""
    mac = hmac.new(
        secret.encode("utf-8"),
        f"v0:{timestamp}:".encode() + body,
        hashlib.sha256,
    )
    return f"v0={mac.hexdigest()}"


def test_verify_slack_signature_accepts_valid_signature() -> None:
    body = b'{"type":"event_callback","event":{"type":"message"}}'
    ts = str(int(time.time()))
    secret = "test_signing_secret_abc123"
    sig = _sign(body, ts, secret)
    assert verify_slack_signature(body, ts, sig, secret) is True


def test_verify_slack_signature_rejects_tampered_body() -> None:
    secret = "test_signing_secret_abc123"
    ts = str(int(time.time()))
    sig = _sign(b'{"a":1}', ts, secret)
    # Different body bytes — signature must not validate.
    assert verify_slack_signature(b'{"a":2}', ts, sig, secret) is False


def test_verify_slack_signature_rejects_wrong_secret() -> None:
    body = b"hello"
    ts = str(int(time.time()))
    sig = _sign(body, ts, "secret-A")
    assert verify_slack_signature(body, ts, sig, "secret-B") is False


def test_verify_slack_signature_rejects_stale_timestamp() -> None:
    body = b"payload"
    secret = "s"
    # 10 minutes in the past — well outside the 5-minute window.
    ts = str(int(time.time()) - 600)
    sig = _sign(body, ts, secret)
    assert verify_slack_signature(body, ts, sig, secret) is False


def test_verify_slack_signature_rejects_future_timestamp() -> None:
    body = b"payload"
    secret = "s"
    ts = str(int(time.time()) + 600)
    sig = _sign(body, ts, secret)
    assert verify_slack_signature(body, ts, sig, secret) is False


def test_verify_slack_signature_rejects_wrong_version_prefix() -> None:
    body = b"x"
    secret = "s"
    ts = str(int(time.time()))
    good_sig = _sign(body, ts, secret)
    # Replace "v0=" with "v1=" — must fail.
    bad_sig = "v1=" + good_sig.split("=", 1)[1]
    assert verify_slack_signature(body, ts, bad_sig, secret) is False


def test_verify_slack_signature_rejects_non_numeric_timestamp() -> None:
    body = b"x"
    secret = "s"
    sig = _sign(body, "1234567890", secret)
    assert verify_slack_signature(body, "not-a-number", sig, secret) is False


def test_verify_slack_signature_rejects_empty_inputs() -> None:
    assert verify_slack_signature(b"x", "", "v0=abc", "s") is False
    assert verify_slack_signature(b"x", "123", "", "s") is False
    assert verify_slack_signature(b"x", "123", "v0=abc", "") is False
    assert verify_slack_signature(b"", "123", "v0=abc", "s") is False


def test_verify_slack_signature_now_s_override_controls_freshness() -> None:
    """The ``now_s`` override lets tests pin clock time."""
    body = b"payload"
    secret = "s"
    sig = _sign(body, "1700000000", secret)
    # Exactly 4 minutes old — fresh.
    assert (
        verify_slack_signature(body, "1700000000", sig, secret, now_s=1700000240)
        is True
    )
    # 6 minutes old — stale.
    assert (
        verify_slack_signature(body, "1700000000", sig, secret, now_s=1700000360)
        is False
    )


# ============================================================================
# format.py — answer formatting
# ============================================================================


def test_format_answer_converts_citations_to_slack_links() -> None:
    url_map = {
        "contract.pdf:p.4": "https://docs.example.com/contract.pdf#page=4",
        "nda.docx§2": "https://docs.example.com/nda.docx#h.2",
    }
    answer = (
        "The cap is USD 1M [contract.pdf:p.4] and confidentiality "
        "lasts 3 years [nda.docx§2]."
    )
    result = format_answer(
        answer,
        cited=["contract.pdf:p.4", "nda.docx§2"],
        url_map=url_map,
    )
    assert len(result["messages"]) == 1
    text = result["messages"][0]["text"]
    # In-text citation becomes a Slack link with the marker as label.
    assert "<https://docs.example.com/contract.pdf#page=4|contract.pdf:p.4>" in text
    assert "<https://docs.example.com/nda.docx#h.2|nda.docx§2>" in text
    # Sources footer also renders the links.
    assert "*Sources:*" in text


def test_format_answer_falls_back_to_bold_when_url_unknown() -> None:
    answer = "Per [file.pdf:p.4] the indemnity is uncapped."
    result = format_answer(answer, cited=["file.pdf:p.4"])
    text = result["messages"][0]["text"]
    # No url_map → bold fallback.
    assert "*file.pdf:p.4*" in text
    # Sources footer also bold.
    assert "*Sources:* *file.pdf:p.4*" in text


def test_format_answer_handles_no_citations() -> None:
    result = format_answer("Just plain text, no citations.", cited=[])
    text = result["messages"][0]["text"]
    assert text == "Just plain text, no citations."
    assert "Sources" not in text


def test_format_answer_escapes_special_chars_in_marker() -> None:
    """Markers with ``<``, ``>``, ``&`` must not break mrkdwn."""
    url_map = {"a<b>&c.pdf": "https://example.com/a%3Cb%3E%26c.pdf"}
    result = format_answer(
        "See [a<b>&c.pdf] for the table.",
        cited=["a<b>&c.pdf"],
        url_map=url_map,
    )
    text = result["messages"][0]["text"]
    # The label must escape the angle brackets + ampersand.
    assert "&lt;" in text
    assert "&gt;" in text
    assert "&amp;" in text


def test_format_answer_splits_long_answers() -> None:
    """Answers over SLACK_MESSAGE_LIMIT must produce multiple messages."""
    # Generate an answer safely under the per-message cap after sources
    # block, but well over the threshold when sources are appended.
    paragraphs = [f"Paragraph {i}: " + ("lorem ipsum " * 60) for i in range(40)]
    answer = "\n\n".join(paragraphs)
    cited = ["contract.pdf:p.4"]
    result = format_answer(answer, cited=cited, header="Acme LLP")
    messages = result["messages"]
    assert len(messages) >= 2, f"expected split, got {len(messages)} messages"
    for msg in messages:
        assert len(msg["text"]) <= 3000  # SLACK_MESSAGE_LIMIT
        assert msg["blocks"]  # each message has block-kit blocks
        assert msg["blocks"][0]["type"] == "section"


def test_format_answer_returns_block_kit_blocks() -> None:
    result = format_answer("Short answer.", cited=["x.pdf:p.1"])
    msg = result["messages"][0]
    assert "blocks" in msg
    section = msg["blocks"][0]
    assert section["type"] == "section"
    assert section["text"]["type"] == "mrkdwn"
    assert "Short answer." in section["text"]["text"]


def test_format_answer_strips_bot_mention_helper() -> None:
    assert strip_bot_mention("<@U0LAN0Z89> what is the cap?") == "what is the cap?"
    # Leading whitespace around the mention is collapsed; trailing
    # whitespace is left intact because the caller does its own strip
    # after extraction.
    assert strip_bot_mention("  <@U0LAN0Z89> hi  ") == "hi  "
    # No mention — unchanged.
    assert strip_bot_mention("plain text") == "plain text"


def test_format_answer_handles_multiline_answer() -> None:
    """Citations on different lines all get rewritten."""
    answer = "Line 1 [a.pdf:p.1]\nLine 2 [b.pdf:p.2]\nLine 3 [a.pdf:p.1]"
    url_map = {
        "a.pdf:p.1": "https://e.com/a.pdf#1",
        "b.pdf:p.2": "https://e.com/b.pdf#2",
    }
    text = format_answer(answer, cited=["a.pdf:p.1", "b.pdf:p.2"], url_map=url_map)[
        "messages"
    ][0]["text"]
    assert "<https://e.com/a.pdf#1|a.pdf:p.1>" in text
    assert "<https://e.com/b.pdf#2|b.pdf:p.2>" in text


# ============================================================================
# handler.py — event handler
# ============================================================================


def test_handler_skips_bot_messages() -> None:
    event = {
        "type": "message",
        "subtype": "bot_message",
        "channel": "C1",
        "bot_id": "B123",
        "text": "hello",
    }
    client = FirmBotClient("http://example", "k")
    with patch.object(FirmBotClient, "query") as mock_query:
        result = handle_message(event, client)
    assert result == []
    mock_query.assert_not_called()


def test_handler_skips_message_edits_and_deletes() -> None:
    for subtype in ("message_changed", "message_deleted"):
        event = {
            "type": "message",
            "subtype": subtype,
            "channel": "C1",
            "text": "edited text",
        }
        client = FirmBotClient("http://example", "k")
        with patch.object(FirmBotClient, "query") as mock_query:
            assert handle_message(event, client) == []
            mock_query.assert_not_called()


def test_handler_skips_empty_text() -> None:
    event = {"type": "message", "channel": "C1", "text": "   "}
    client = FirmBotClient("http://example", "k")
    with patch.object(FirmBotClient, "query") as mock_query:
        assert handle_message(event, client) == []
        mock_query.assert_not_called()


def test_handler_returns_error_message_when_firm_slug_missing() -> None:
    event = {
        "type": "message",
        "channel": "C1",
        "user": "U1",
        "text": "What is the cap?",
    }
    client = FirmBotClient("http://example", "k")
    with patch.object(FirmBotClient, "query") as mock_query:
        result = handle_message(event, client)
    assert len(result) == 1
    assert "no firm" in result[0]["text"].lower()
    mock_query.assert_not_called()


def test_handler_queries_firm_bot_and_returns_formatted_response() -> None:
    event = {
        "type": "app_mention",
        "channel": "C1",
        "user": "U1",
        "text": "<@U0LAN0Z89> what is the cap on liability?",
        "firm_slug": "acme",
        "header": "Acme LLP",
        "url_map": {"contract.pdf:p.4": "https://docs/contract.pdf#page=4"},
    }
    expected_payload = {
        "answer": "The cap is USD 1M [contract.pdf:p.4].",
        "cited": ["contract.pdf:p.4"],
        "hits": [],
        "issues": [],
        "summary": "ok",
        "confidence": 0.92,
    }
    client = FirmBotClient("http://example", "k")
    with patch.object(
        FirmBotClient, "query", return_value=expected_payload
    ) as mock_query:
        result = handle_message(event, client)

    mock_query.assert_called_once_with(
        "acme", "what is the cap on liability?", history=None
    )
    assert len(result) >= 1
    text = result[0]["text"]
    assert "USD 1M" in text
    assert "<https://docs/contract.pdf#page=4|contract.pdf:p.4>" in text
    assert "*Acme LLP*" in text
    assert "*Sources:*" in text


def test_handler_returns_user_facing_error_on_firm_bot_failure() -> None:
    event = {
        "type": "message",
        "channel": "C1",
        "user": "U1",
        "text": "hi",
        "firm_slug": "acme",
    }
    client = FirmBotClient("http://example", "k")
    with patch.object(
        FirmBotClient,
        "query",
        side_effect=FirmBotClientError("boom", status_code=503, body={"err": "x"}),
    ):
        result = handle_message(event, client)
    assert len(result) == 1
    assert "firm-bot error" in result[0]["text"]
    assert "503" in result[0]["text"]


# ============================================================================
# bot.py — FirmBotClient
# ============================================================================


class _FakeResponse:
    """Minimal stand-in for ``http.client.HTTPResponse``."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        # urllib invokes close() via context-manager __exit__ AND the
        # tempfile deallocator path — provide a no-op so the GC
        # doesn't complain.
        return None

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_: Any) -> None:
        return None


def test_firm_bot_client_query_builds_correct_request() -> None:
    client = FirmBotClient("http://firm-bot:7860/", "secret-key-xyz")
    captured: dict[str, Any] = {}

    def fake_urlopen(req: Any, timeout: float) -> _FakeResponse:
        captured["url"] = req.full_url
        captured["method"] = req.method
        # urllib normalises header names ("Content-Type" → "Content-type")
        # via email.message; use a case-insensitive lookup.
        captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
        captured["body"] = req.data
        captured["timeout"] = timeout
        return _FakeResponse(
            json.dumps(
                {
                    "answer": "42",
                    "cited": ["file.pdf:p.4"],
                    "hits": [],
                    "issues": [],
                    "summary": "ok",
                    "confidence": 0.99,
                }
            ).encode("utf-8")
        )

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = client.query("acme", "What is the cap?", history=None, k=4)

    assert captured["url"] == "http://firm-bot:7860/v1/firms/acme/query"
    assert captured["method"] == "POST"
    assert captured["headers"]["authorization"] == "Bearer secret-key-xyz"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["timeout"] == 60.0
    body = json.loads(captured["body"])
    assert body == {"question": "What is the cap?", "history": None, "k": 4}
    assert result["answer"] == "42"


def test_firm_bot_client_list_firms_returns_firms_array() -> None:
    client = FirmBotClient("http://h:7860", "k")
    payload = {"firms": [{"slug": "acme"}, {"slug": "globex"}], "data_dir": "/x"}
    with patch(
        "urllib.request.urlopen",
        return_value=_FakeResponse(json.dumps(payload).encode("utf-8")),
    ):
        firms = client.list_firms()
    assert firms == [{"slug": "acme"}, {"slug": "globex"}]


def test_firm_bot_client_handles_non_200_responses() -> None:
    import urllib.error

    client = FirmBotClient("http://h:7860", "k")
    err = urllib.error.HTTPError(
        "http://h:7860/v1/firms/acme/query",
        404,
        "Not Found",
        {},
        _FakeResponse(b'{"detail":"no such firm"}'),
    )
    with (
        patch("urllib.request.urlopen", side_effect=err),
        pytest.raises(FirmBotClientError) as ei,
    ):
        client.query("acme", "hi")
    assert ei.value.status_code == 404
    assert ei.value.body == {"detail": "no such firm"}
    assert "404" in str(ei.value)


def test_firm_bot_client_handles_transport_errors() -> None:
    import urllib.error

    client = FirmBotClient("http://h:7860", "k")
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ), pytest.raises(FirmBotClientError) as ei:
        client.query("acme", "hi")
    assert ei.value.status_code is None
    assert "unreachable" in str(ei.value).lower()


def test_firm_bot_client_health_returns_true_on_2xx() -> None:
    client = FirmBotClient("http://h:7860", "k")
    with patch(
        "urllib.request.urlopen",
        return_value=_FakeResponse(b'{"status":"ok"}'),
    ):
        assert client.health() is True


# ============================================================================
# public-API smoke test
# ============================================================================


def test_public_api_imports_cleanly() -> None:
    """The package exports everything documented in the spec."""
    from firm_bot.integrations import slack as slack_pkg
    from firm_bot.integrations.slack import (
        FirmBotClient as _C,
    )
    from firm_bot.integrations.slack import (
        format_answer as _f,
    )
    from firm_bot.integrations.slack import (
        handle_message as _h,
    )
    from firm_bot.integrations.slack import (
        verify_slack_signature as _v,
    )

    assert slack_pkg.FirmBotClient is _C
    assert slack_pkg.format_answer is _f
    assert slack_pkg.handle_message is _h
    assert slack_pkg.verify_slack_signature is _v
