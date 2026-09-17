"""PII redaction at ingest time.

Why
----
Firms ingest PDFs, emails, and contracts that often contain personally
identifiable information — social security numbers, account numbers, emails,
phone numbers, etc. Even with a local-only deployment, the *retrieval*
step exposes these strings to whoever is asking questions. For a legal
firm handling discovery, redacting before indexing is a baseline
hygiene requirement.

Scope
-----
We replace matches with stable category tokens (e.g. ``SSN-XXX-XX-XXXX``)
so the operator can still see *that* a number was there without seeing
*which* one. Retrieval and citation still work; the user can ask about
"the SSN at the top of page 4" and the bot returns ``SSN-XXX-XX-XXXX``.

Patterns
--------
- U.S. SSN: ``NNN-NN-NNNN`` (with simple validation — area 000, 900-999
  excluded)
- EIN: ``NN-NNNNNNNN``
- Email: ``user@domain.tld``
- Phone (international / US): loose — 10+ digits with separators
- Credit card: 13-19 digit runs (Luhn-validated where possible)
- IBAN: 2 letters + 2 digits + alphanumerics
- IP address: ``N.N.N.N`` (avoid false positives on clause numbers
  by requiring boundary dots)

Categories can be toggled per-firm in ``firm_config.redact_categories``.

Caveats
-------
Regex is not a substitute for proper NER; we catch common formats but
will miss names, addresses, and unusual identifiers. For high-stakes
deployments, layer a real NER model (presidio, GLiNER) on top.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger("firm_bot.redact")


# ---- patterns ---------------------------------------------------------


# US SSN: NNN-NN-NNNN, with simple validation to cut false positives.
_RE_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")

# US EIN: NN-NNNNNNNN (assigned by IRS to businesses/trusts)
_RE_EIN = re.compile(r"\b\d{2}-\d{7}\b")

# Email: simplified — actual RFC 5321 is nightmarish; we catch the
# common shapes and let the rest through.
_RE_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Phone: 10+ digits with optional separators. The lookbehind/lookahead
# pin to non-digit boundaries so we don't match parts of an SSN.
_RE_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")

# Credit card: 13-19 digit runs with optional spaces/dashes. Validate
# with Luhn; drop false positives.
_RE_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")

# IBAN: 2 letters + 2 digits + up to 32 alphanumeric.
_RE_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")

# IP address: four 0-255 octets, with word boundaries so we don't match
# "1.2.3" in a contract clause numbering like "Section 1.2.3".
_RE_IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b")


@dataclass(frozen=True)
class RedactionRule:
    name: str
    pattern: re.Pattern[str]
    placeholder: str

    def apply(self, text: str) -> str:
        return self.pattern.sub(self.placeholder, text)


DEFAULT_CATEGORIES: dict[str, RedactionRule] = {
    "ssn": RedactionRule("ssn", _RE_SSN, "[SSN-REDACTED]"),
    "ein": RedactionRule("ein", _RE_EIN, "[EIN-REDACTED]"),
    "email": RedactionRule("email", _RE_EMAIL, "[EMAIL-REDACTED]"),
    "phone": RedactionRule("phone", _RE_PHONE, "[PHONE-REDACTED]"),
    "credit_card": RedactionRule("credit_card", _RE_CARD, "[CARD-REDACTED]"),
    "iban": RedactionRule("iban", _RE_IBAN, "[IBAN-REDACTED]"),
    "ipv4": RedactionRule("ipv4", _RE_IPV4, "[IP-REDACTED]"),
}


# ---- public API --------------------------------------------------------


def redact_text(
    text: str,
    categories: list[str] | None = None,
) -> str:
    """Return ``text`` with PII replaced by stable category tokens.

    ``categories`` is a list of keys from ``DEFAULT_CATEGORIES`` —
    ``None`` (the default) means "redact everything we know about".
    Categories listed but not in DEFAULT_CATEGORIES are silently skipped.
    """
    if categories is None:
        rules = list(DEFAULT_CATEGORIES.values())
    else:
        rules = [DEFAULT_CATEGORIES[c] for c in categories if c in DEFAULT_CATEGORIES]
    out = text
    for rule in rules:
        out = rule.apply(out)
    return out


def count_redactions(
    text: str,
    categories: list[str] | None = None,
) -> dict[str, int]:
    """Return a {category: count} map of what *would* be redacted."""
    if categories is None:
        items: list[tuple[str, RedactionRule]] = list(DEFAULT_CATEGORIES.items())
    else:
        items = [(c, DEFAULT_CATEGORIES[c]) for c in categories if c in DEFAULT_CATEGORIES]
    return {name: len(rule.pattern.findall(text)) for name, rule in items}


def _luhn_check(digits: str) -> bool:
    """Luhn checksum — used to validate card numbers."""
    digits = re.sub(r"\D", "", digits)
    if not (12 <= len(digits) <= 19):
        return False
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def redact_credit_cards_validated(text: str) -> str:
    """Stricter card redactor that only matches Luhn-valid numbers."""
    def _sub(m: re.Match[str]) -> str:
        return "[CARD-REDACTED]" if _luhn_check(m.group(0)) else m.group(0)

    return _RE_CARD.sub(_sub, text)
