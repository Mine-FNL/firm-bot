"""Tests for the PII redaction module."""

from __future__ import annotations


def test_redact_ssn() -> None:
    from firm_bot.redact import redact_text

    text = "SSN 123-45-6789 is on file."
    out = redact_text(text, ["ssn"])
    assert "123-45-6789" not in out
    assert "[SSN-REDACTED]" in out


def test_redact_email() -> None:
    from firm_bot.redact import redact_text

    text = "Contact alice@example.com or bob+filter@x.io for details."
    out = redact_text(text, ["email"])
    assert "alice@example.com" not in out
    assert "bob+filter@x.io" not in out
    assert out.count("[EMAIL-REDACTED]") == 2


def test_redact_phone() -> None:
    from firm_bot.redact import redact_text

    text = "Phone: (555) 123-4567. Alt: +1-555-123-4567."
    out = redact_text(text, ["phone"])
    assert "555-123-4567" not in out
    # two phones, both redacted
    assert out.count("[PHONE-REDACTED]") == 2


def test_redact_credit_card_luhn_only() -> None:
    from firm_bot.redact import redact_credit_cards_validated

    # Luhn-valid test card from spec
    text = "Card: 4111 1111 1111 1111. Random: 1234 5678 9012 3456."
    out = redact_credit_cards_validated(text)
    assert "[CARD-REDACTED]" in out
    # 4111 1111 1111 1111 is the canonical Luhn-valid test number
    # 1234 5678 9012 3456 is NOT Luhn-valid, should pass through
    assert "4111 1111 1111 1111" not in out


def test_redact_iban() -> None:
    from firm_bot.redact import redact_text

    text = "IBAN: GB29NWBK60161331926819 is the account."
    out = redact_text(text, ["iban"])
    assert "GB29NWBK60161331926819" not in out
    assert "[IBAN-REDACTED]" in out


def test_redact_ipv4() -> None:
    from firm_bot.redact import redact_text

    text = "Server 192.168.1.42 is on the network. Section 1.2.3 says..."
    out = redact_text(text, ["ipv4"])
    assert "192.168.1.42" not in out
    # Make sure clause numbering is NOT redacted
    assert "1.2.3" in out


def test_redact_all_categories_by_default() -> None:
    from firm_bot.redact import redact_text

    text = "SSN 123-45-6789. Email: x@y.com. IP: 10.0.0.1."
    out = redact_text(text)
    assert "123-45-6789" not in out
    assert "x@y.com" not in out
    assert "10.0.0.1" not in out


def test_redact_empty_categories_disables() -> None:
    """An empty list means 'redact nothing'."""
    from firm_bot.redact import redact_text

    text = "SSN 123-45-6789 stays as-is."
    out = redact_text(text, [])
    assert "123-45-6789" in out


def test_count_redactions() -> None:
    from firm_bot.redact import count_redactions

    text = "alice@x.com bob@y.com has phone 555-123-4567."
    counts = count_redactions(text, ["email", "phone"])
    assert counts["email"] == 2
    assert counts["phone"] == 1


def test_unknown_category_is_ignored() -> None:
    from firm_bot.redact import redact_text

    text = "SSN 123-45-6789"
    # unknown category should not affect the SSN
    out = redact_text(text, ["unknown-category"])
    assert "123-45-6789" in out


def test_ssn_validation_excludes_impossible_numbers() -> None:
    """SSN 000-12-3456 and 666-12-3456 and 900-12-3456 should not match."""
    from firm_bot.redact import redact_text

    text = "Bad SSNs: 000-12-3456, 666-12-3456, 900-12-3456"
    out = redact_text(text, ["ssn"])
    # None of these should be redacted because area 000/666/9xx is invalid
    assert "000-12-3456" in out
    assert "666-12-3456" in out
    assert "900-12-3456" in out
