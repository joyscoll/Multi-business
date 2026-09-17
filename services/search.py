"""Forgiving catalogue search helpers.

Exact/partial matches are preferred, with a lightweight fuzzy fallback for
common typos. This intentionally works in Python so it remains database-agnostic
across the project's SQLite/Postgres development and production setups.
"""
import re
import unicodedata
from difflib import SequenceMatcher


def normalize_text(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return value


def _word_similarity(query_words, text_words):
    if not query_words or not text_words:
        return 0.0
    scores = []
    for qw in query_words:
        best = max((SequenceMatcher(None, qw, tw).ratio() for tw in text_words), default=0.0)
        scores.append(best)
    return sum(scores) / len(scores)


def _score(query, product, aliases=()):
    q = normalize_text(query)
    if not q:
        return 0.0
    fields = [
        (normalize_text(product.name), 1.00),
        (normalize_text(product.brand), 0.84),
        (normalize_text(product.search_keywords), 0.72),
        (normalize_text(product.sku), 0.60),
        (normalize_text(product.barcode), 0.60),
    ]
    for alias in aliases or ():
        fields.append((normalize_text(alias), 0.93))

    q_words = q.split()
    best = 0.0
    for text, weight in fields:
        if not text:
            continue
        if q == text:
            return 1.0
        if q in text:
            best = max(best, 0.97 * weight)
            continue
        text_words = text.split()
        if q_words and all(any(qw in tw for tw in text_words) for qw in q_words):
            best = max(best, 0.93 * weight)
        similarity = SequenceMatcher(None, q, text).ratio()
        token_similarity = _word_similarity(q_words, text_words)
        best = max(best, similarity * weight, token_similarity * weight * 0.98)
    return best


def forgiving_rank(rows, query, aliases_by_product=None, limit=300, minimum=0.58):
    """Return rows ranked by exact/partial/fuzzy relevance.

    The caller should already constrain rows to the correct store/availability.
    """
    if not query:
        return list(rows)[:limit]
    aliases_by_product = aliases_by_product or {}
    scored = []
    for row in rows:
        score = _score(query, row.product, aliases_by_product.get(row.product_id, ()))
        if score >= minimum:
            scored.append((score, row.product.name.lower(), row))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [row for _, _, row in scored[:limit]]
