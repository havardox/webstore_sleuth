from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

import extruct
from pydantic import ValidationError

from webstore_sleuth.schemas import Product
from webstore_sleuth.utils.converters import parse_price, parse_iso_date, ensure_list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_first_nonempty(*args) -> str | None:
    """Returns the first string argument that is not None or empty."""
    for a in args:
        if a is None:
            continue
        if isinstance(a, str):
            s = a.strip()
            if s:
                return s
        elif isinstance(a, (int, float)):
            return str(a)
    return None


def _normalize_type_strings(t: str | list[str] | None) -> list[str]:
    """Normalizes schema types to lowercase class names (e.g. 'http://schema.org/Product' -> 'product')."""
    if not t:
        return []

    raw = t if isinstance(t, list) else [t]

    normalized: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        # Extract last part of URL or hashtag
        token = item.strip().split("/")[-1].split("#")[-1]
        normalized.append(token.lower())

    return normalized


# ---------------------------------------------------------------------------
# Data Normalization (Microdata & JSON-LD)
# ---------------------------------------------------------------------------
def _convert_microdata_value(val: Any) -> Any:
    """Recursively simplifies microdata structures."""
    if isinstance(val, list):
        return [_convert_microdata_value(v) for v in val]

    if isinstance(val, dict):
        if "properties" in val:
            # Flatten 'properties' up one level
            props = val.get("properties") or {}
            out: dict[str, Any] = {}
            for k, v in props.items():
                # Microdata properties are usually lists; take first if exists
                extracted = v[0] if isinstance(v, list) and v else v
                out[k] = _convert_microdata_value(extracted)
            return out

        return {k: _convert_microdata_value(v) for k, v in val.items()}

    return val


def _normalize_microdata_item(item: dict[str, Any]) -> dict[str, Any]:
    """Converts a microdata item into a JSON-LD style dictionary with @type."""
    types: list[str] = []

    if "type" in item:
        types.extend(_normalize_type_strings(item.get("type")))

    properties = item.get("properties", {}) or {}
    normalized: dict[str, Any] = {"@type": list(set(types))}

    for k, v in properties.items():
        normalized[k] = _convert_microdata_value(v)

    return normalized


def _flatten_jsonld_graph(entry: Any) -> list[dict[str, Any]]:
    """Flattens nested JSON-LD graphs into a list of nodes."""
    nodes: list[dict[str, Any]] = []

    def _recurse(obj: Any) -> None:
        if isinstance(obj, list):
            for i in obj:
                _recurse(i)
        elif isinstance(obj, dict):
            # If it's a node with @type, keep it
            if "@type" in obj:
                nodes.append(obj)

            # Traverse typical nesting fields
            if "@graph" in obj:
                _recurse(obj["@graph"])

            # Sometimes products are nested in 'contains' or 'mainEntity'
            for field in ("contains", "mainEntity", "hasVariant"):
                if field in obj:
                    _recurse(obj[field])

    _recurse(entry)
    return nodes


# ---------------------------------------------------------------------------
# Extraction Logic
# ---------------------------------------------------------------------------
def _choose_offer(offers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """
    Selects the best offer.
    Priority:
    1. InStock AND has Price
    2. InStock (no price info)
    3. Any other offer with Price
    4. First available
    """
    if not offers:
        return None

    def sort_key(o: dict[str, Any]) -> tuple[int, int]:
        # Determine Availability Score
        avail = str(o.get("availability") or "").lower()

        if "instock" in avail or "in_stock" in avail:
            avail_score = 0
        elif "outofstock" in avail or "soldout" in avail:
            avail_score = 2
        else:
            avail_score = 1  # Unknown/Preorder

        # Determine Price Presence (prefer offers with price)
        has_price = (
            0 if (o.get("price") or o.get("lowPrice") or o.get("highPrice")) else 1
        )

        return avail_score, has_price

    return min(offers, key=sort_key)


GTIN_KEYS = ("gtin13", "gtin14", "gtin", "gtin8", "ean", "isbn")


def _extract_ean_from_product(prod: dict[str, Any]) -> str | None:
    """Finds EAN/GTIN in product or its offers."""

    # Check top-level
    for key in GTIN_KEYS:
        if val := prod.get(key):
            return str(val)

    # Check offers
    offers = ensure_list(prod.get("offers"))
    for o in offers:
        if not isinstance(o, dict):
            continue
        for key in GTIN_KEYS:
            if val := o.get(key):
                return str(val)

    # Check complex identifiers (PropertyValue)
    identifiers = ensure_list(prod.get("identifier") or prod.get("additionalProperty"))
    for ident in identifiers:
        if isinstance(ident, dict):
            pid = str(ident.get("propertyID") or ident.get("name") or "").lower()
            val = ident.get("value")

            # If the property name looks like EAN/GTIN
            if any(k in pid for k in GTIN_KEYS) and val:
                return str(val)

            # Check keys inside the identifier object itself
            for k in GTIN_KEYS:
                if v := ident.get(k):
                    return str(v)

    return None


def _is_active_check(
    prod: dict[str, Any],
    offer: dict[str, Any] | None,
    price: Decimal | None,
) -> bool:
    """Determines if product is buyable based on stock, dates, and price."""

    # 1. Check Availability Strings
    # Prefer offer availability, fallback to product
    avail_raw = (offer.get("availability") if offer else None) or prod.get(
        "availability"
    )
    if avail_raw:
        # Schema.org URLs often look like http://schema.org/InStock
        token = str(avail_raw).split("/")[-1].lower()
        if any(
            x in token for x in ("outofstock", "soldout", "discontinued", "unavailable")
        ):
            return False
        if any(x in token for x in ("instock", "in_stock", "available")):
            return True

    # 2. Check Dates (validFrom / validThrough)
    now = datetime.now(timezone.utc)

    def get_date(k: str) -> datetime | None:
        return parse_iso_date((offer.get(k) if offer else None) or prod.get(k))

    valid_from = get_date("validFrom")
    valid_through = get_date("validThrough") or get_date("priceValidUntil")

    if valid_from and now < valid_from:
        return False
    if valid_through and now > valid_through:
        return False

    # 3. Fallback: If we have a price > 0, assume active
    if price is not None and price > 0:
        return True

    # Default to False if ambiguous
    return False


def _extract_from_extruct_data(data: dict[str, Any], url: str) -> Product | None:
    """Finds the best matching Product node from extracted metadata."""

    candidates: list[dict[str, Any]] = []

    # 1. Collect JSON-LD candidates
    for entry in ensure_list(data.get("json-ld", [])):
        nodes = _flatten_jsonld_graph(entry)
        for node in nodes:
            # Normalize type for consistent checking
            node["@type"] = _normalize_type_strings(
                node.get("@type") or node.get("type")
            )
            candidates.append(node)

    # 2. Collect Microdata candidates
    for item in ensure_list(data.get("microdata", [])):
        if isinstance(item, dict):
            candidates.append(_normalize_microdata_item(item))

    # 3. Filter for Products
    product_candidates: list[dict[str, Any]] = []
    for c in candidates:
        types = c.get("@type", [])
        if any("product" in t for t in types):
            product_candidates.append(c)

    # 4. Fallback: Look for items with prices/offers even if not strictly typed "Product"
    if not product_candidates:
        for c in candidates:
            if c.get("offers") or c.get("sku") or c.get("mpn"):
                product_candidates.append(c)

    if not product_candidates:
        return None

    # 5. Score Candidates to find the "Main" product
    def candidate_score(p: dict[str, Any]) -> int:
        score = 0
        if p.get("name"):
            score += 5
        if p.get("offers"):
            score += 5
        if p.get("image"):
            score += 1
        if p.get("description"):
            score += 1
        return -score  # Use negative for min() to pick highest score

    best_prod = min(product_candidates, key=candidate_score)

    # 6. Extract Fields
    title = _get_first_nonempty(
        best_prod.get("name"),
        best_prod.get("title"),
        best_prod.get("headline"),
    )

    offers = ensure_list(best_prod.get("offers"))
    chosen_offer = _choose_offer(offers)

    # Price Extraction
    price_val = None
    currency = None

    # Try offer first
    if chosen_offer:
        price_val = parse_price(
            _get_first_nonempty(
                chosen_offer.get("price"),
                chosen_offer.get("priceAmount"),
                chosen_offer.get("amount"),
                chosen_offer.get("lowPrice"),  # For ranges, take low
            )
        )
        currency = _get_first_nonempty(
            chosen_offer.get("priceCurrency"),
            chosen_offer.get("currency"),
        )

    # Fallback to product
    if price_val is None:
        price_val = parse_price(
            _get_first_nonempty(
                best_prod.get("price"),
                best_prod.get("priceAmount"),
            )
        )

    if currency is None:
        currency = _get_first_nonempty(
            best_prod.get("priceCurrency"),
            best_prod.get("currency"),
        )

    return Product(
        url=url,
        title=title or "",  # Pydantic requires string, handle empty later if needed
        description=_get_first_nonempty(best_prod.get("description")),
        price=price_val,
        currency=currency,
        ean=_extract_ean_from_product(best_prod),
        mpn=_get_first_nonempty(best_prod.get("mpn")),  # SKU is often used as MPN
        is_active=_is_active_check(best_prod, chosen_offer, price_val),
    )


def extract_product(
    html_content: str,
    url: str,
    title: str | None = None,
    description: str | None = None,
    price: str | Decimal | float | None = None,
    currency: str | None = None,
    ean: str | None = None,
    mpn: str | None = None,
) -> Product | None:
    """
    Orchestrates product extraction.
    1. Extracts schema.org data.
    2. Overrides with manual arguments.
    3. Validates final object.
    """

    # 1. Extruct Extraction
    extracted_product: Product | None = None
    try:
        data = extruct.extract(
            html_content,
            base_url=url,
            syntaxes=["json-ld", "microdata"],
            errors="ignore",  # Don't crash on bad JSON
        )
        extracted_product = _extract_from_extruct_data(data, url=url)
    except (ValueError, TypeError):
        # If extruct fails entirely, we proceed with manual overrides only
        extracted_product = None

    if extracted_product:
        # Convert to dict, excluding defaults/Nones to allow clean overriding
        final_values = extracted_product.model_dump(exclude_none=True)
    else:
        final_values = {}

    # 2. Apply Overrides
    # Always ensure URL is present
    final_values["url"] = url

    if title:
        final_values["title"] = title
    if description:
        final_values["description"] = description
    if price:
        final_values["price"] = price
    if currency:
        final_values["currency"] = currency
    if ean:
        final_values["ean"] = ean
    if mpn:
        final_values["mpn"] = mpn

    # 3. Check Validity (Minimum viable product needs a title)
    if not final_values.get("title"):
        return None

    try:
        return Product(**final_values)
    except ValidationError:
        # Log this in a real system
        return None
