"""Lexical retrieval (BM25) over a firm's chunk corpus.

We tokenise with a domain-aware pattern:
- lowercased
- split on non-alphanumeric / underscore boundaries (so ``Q3_2024``
  and ``q3 2024`` match)
- keep tokens of length ≥ 2
- drop a small English + legal-domain stopword list

Stopword list is deliberately short. Generic stopword lists (lucene, nltk)
over-strip from legal prose ("the", "of", "and" carry semantic weight in
contract headers like "Limitation of Liability").
"""

from __future__ import annotations

import re
from typing import Any

# A conservative stopword list — keep generic words that hurt BM25 in
# legal/business prose. Far shorter than the 150-word nltk set on purpose.
_LEGAL_STOPWORDS = frozenset(
    {
        "the",
        "of",
        "and",
        "a",
        "an",
        "in",
        "to",
        "for",
        "is",
        "are",
        "be",
        "that",
        "this",
        "with",
        "as",
        "by",
        "at",
        "from",
    }
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]+")


def tokenise(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in _LEGAL_STOPWORDS and len(t) >= 2]


def bm25_search(
    bm25: Any,
    meta: list[dict[str, object]],
    query: str,
    k: int,
) -> list[tuple[str, float, int]]:
    """Run a BM25 query and return ranked chunk IDs.

    ``meta`` is the parallel array saved alongside the BM25 corpus. Each
    entry may carry a ``chunk_id``; otherwise we synthesise one from
    ``parent_doc_id`` + ``chunk_index``.

    Returns ``(chunk_id, score, rank)`` sorted by score desc.
    """
    if bm25 is None or not meta:
        return []
    q_tokens = tokenise(query)
    if not q_tokens:
        return []
    scores = bm25.get_scores(q_tokens)
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    out: list[tuple[str, float, int]] = []
    for rank, idx in enumerate(order[:k]):
        if scores[idx] <= 0:
            break
        cid_obj = meta[idx].get("chunk_id")
        if cid_obj:
            cid = str(cid_obj)
        else:
            parent = str(meta[idx].get("parent_doc_id") or "meta")
            i = meta[idx].get("chunk_index", idx)
            cid = f"{parent}:{i}"
        out.append((cid, float(scores[idx]), rank))
    return out
