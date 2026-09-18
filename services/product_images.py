"""Safe product-image resolution.

The resolver only stores a remote image when the marketplace/product search
returns an image with a strong name/brand match. It never substitutes a random
category image for an exact product identity.
"""

from functools import lru_cache
from urllib.parse import urlencode
import re

import requests
from flask import current_app


def _tokens(value: str):
    return [t for t in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(t) > 1]


def _score(query_name: str, query_brand: str, candidate_name: str, candidate_brand: str):
    q_tokens = set(_tokens(query_name))
    c_tokens = set(_tokens(candidate_name))
    if not q_tokens or not c_tokens:
        return 0.0
    # Drop very generic packaging terms from the name-match component.
    ignored = {"pack", "piece", "pcs", "unit", "box", "bottle", "bag", "tin", "jar", "can", "set", "s", "kg", "g", "ml", "l"}
    q_core = q_tokens - ignored
    c_core = c_tokens - ignored
    overlap = len(q_core & c_core) / max(1, len(q_core))
    phrase = 0.0
    q_norm = " ".join(_tokens(query_name))
    c_norm = " ".join(_tokens(candidate_name))
    if q_norm and (q_norm in c_norm or c_norm in q_norm):
        phrase = 0.25
    brand_bonus = 0.0
    if query_brand and query_brand.lower() not in {"various", "fresh produce", "fresh meat", "fresh fish"}:
        qb = " ".join(_tokens(query_brand))
        cb = " ".join(_tokens(candidate_brand or ""))
        if qb and (qb == cb or qb in cb or cb in qb):
            brand_bonus = 0.25
        else:
            # A named-brand product without a matching brand is not trusted.
            return 0.0
    return min(1.0, overlap * 0.7 + phrase + brand_bonus)


@lru_cache(maxsize=1536)
def lookup_exact_image(name: str, brand: str):
    endpoints = [
        current_app.config.get("PRODUCT_IMAGE_LOOKUP_URL", "https://world.openfoodfacts.org/cgi/search.pl"),
        "https://world.openbeautyfacts.org/cgi/search.pl",
        "https://world.openproductsfacts.org/cgi/search.pl",
    ]
    params = {
        "search_terms": f"{brand} {name}".strip(),
        "search_simple": "1",
        "action": "process",
        "json": "1",
        "page_size": "12",
        "fields": "product_name,brands,image_front_url,image_url,code",
        "sort_by": "relevance",
    }
    best = None
    for endpoint in endpoints:
        try:
            response = requests.get(
                endpoint,
                params=params,
                timeout=float(current_app.config.get("PRODUCT_IMAGE_LOOKUP_TIMEOUT", 6)),
                headers={"User-Agent": "Denmart/17 product-photo-resolver"},
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            continue
        for candidate in payload.get("products") or []:
            image = candidate.get("image_front_url") or candidate.get("image_url")
            candidate_name = candidate.get("product_name") or ""
            candidate_brand = candidate.get("brands") or ""
            if not image or not str(image).startswith("https://"):
                continue
            score = _score(name, brand, candidate_name, candidate_brand)
            if score >= 0.70 and (best is None or score > best[0]):
                best = (score, image, candidate)
        if best and best[0] >= 0.88:
            break
    return best


def resolve_product_image(product):
    """Return a trusted exact-match image URL or None; cache nothing on miss."""
    if product.image_url and str(product.image_url).strip():
        return product.image_url
    result = lookup_exact_image(product.name, product.brand or "")
    if not result:
        return None
    return result[1]
