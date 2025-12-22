from decimal import Decimal
from datetime import datetime, timezone
from typing import Any

import extruct
from pydantic import ValidationError

from webstore_sleuth.schemas import Product
from webstore_sleuth.utils.converters import (
    parse_price,
    parse_iso_date,
    ensure_list,
)
from webstore_sleuth.product_schema_normalizer import SchemaNormalizer


GTIN_KEYS = ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "ean", "isbn")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_first_nonempty(*args) -> str | None:
    """
    Returns the first non-empty string from the arguments.
    Useful for fallback logic (e.g., check 'price', then 'highPrice').
    """
    for a in args:
        if isinstance(a, str) and a.strip():
            return a.strip()
        if isinstance(a, (int, float, Decimal)):
            return str(a)
    return None


# ---------------------------------------------------------------------------
# Product Candidate
# ---------------------------------------------------------------------------
class ProductCandidate:
    """
    Wraps a normalized dictionary to provide heuristic extraction methods
    exposed as properties.
    """

    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.offers = [o for o in ensure_list(raw.get("offers")) if isinstance(o, dict)]

    @property
    def title(self) -> str | None:
        """Extracts the product name."""
        return get_first_nonempty(self.raw.get("name"))

    @property
    def description(self) -> str | None:
        """Extracts the product description."""
        return get_first_nonempty(self.raw.get("description"))

    @property
    def mpn(self) -> str | None:
        """
        Locates the Manufacturer Part Number (MPN).
        Checks the explicit 'mpn' field first, then searches through generic
        'identifier' lists for properties labeled 'mpn'.
        """
        # Check explicit field first
        val = self.raw.get("mpn")
        if val:
            return str(val)

        # Fallback: Many sites hide MPN inside a generic "identifier" list.
        # Structure: [{"@type": "PropertyValue", "propertyID": "mpn", "value": "123"}]
        for ident in ensure_list(
            self.raw.get("identifier") or self.raw.get("additionalProperty")
        ):
            if isinstance(ident, dict):
                pid = str(ident.get("propertyID") or ident.get("name") or "").lower()
                if pid in ("mpn", "manufacturer part number"):
                    return str(ident.get("value"))
        return None

    @property
    def best_offer(self) -> dict[str, Any]:
        """
        Selects the single most relevant offer from the list of offers.

        Selection Logic:
        1. Availability: InStock > OutOfStock > PreOrder > Unknown.
        2. Price presence: Offers with a price are preferred over those without.
        """
        if not self.offers:
            return {}

        def score(o: dict[str, Any]) -> tuple[int, int]:
            avail = str(o.get("availability") or "").lower()
            # 0 = Best (InStock), 2 = Worst (OutOfStock/SoldOut), 1 = Unknown
            avail_score = (
                0
                if "instock" in avail
                else (2 if any(x in avail for x in ("outofstock", "soldout")) else 1)
            )
            # Tie-breaker: Prefer offers that actually have a price (0) over those that don't (1)
            return avail_score, (0 if o.get("price") else 1)

        return min(self.offers, key=score)

    @property
    def price(self) -> Decimal | None:
        """
        Extracts the numeric price from the best available offer.
        Checks both the direct 'price' field and nested 'priceSpecification' objects.
        """
        offer = self.best_offer
        # Some schemas put price in 'priceSpecification' object
        price_spec = offer.get("priceSpecification") or {}

        raw_price = get_first_nonempty(offer.get("price"), price_spec.get("price"))
        return parse_price(raw_price)

    @property
    def currency(self) -> str | None:
        """
        Extracts the currency code (e.g., 'USD', 'EUR') from the best available offer.
        """
        offer = self.best_offer
        price_spec = offer.get("priceSpecification") or {}
        return get_first_nonempty(
            offer.get("priceCurrency"), price_spec.get("priceCurrency")
        )

    @property
    def ean(self) -> str | None:
        """
        Searches for a Global Trade Item Number (GTIN/EAN/ISBN).

        Search Order:
        1. Explicit keys (gtin, ean, isbn) in the root product object.
        2. Explicit keys in the best offer object.
        3. Generic 'identifier' or 'additionalProperty' lists.
        """
        # Search for GTINs in the product root AND the selected offer
        sources = [self.raw] + ([self.best_offer] if self.offers else [])
        for source in sources:
            for k in GTIN_KEYS:
                if val := source.get(k):
                    return str(val)

        # Fallback: Check generic identifiers
        for ident in ensure_list(
            self.raw.get("identifier") or self.raw.get("additionalProperty")
        ):
            if isinstance(ident, dict):
                pid = str(ident.get("propertyID") or ident.get("name") or "").lower()
                if any(k in pid for k in ("gtin", "ean", "isbn")):
                    return str(ident.get("value"))
        return None

    @property
    def is_active(self) -> bool:
        """
        Determines if the product is currently buyable.

        Heuristics:
        1. Checks explicit strings (e.g., 'OutOfStock', 'Discontinued').
        2. Checks 'validFrom' and 'validThrough' date ranges against current UTC time.
        3. Checks if a valid price (> 0) is currently detectable.
        """
        offer = self.best_offer
        token = str(offer.get("availability") or "").split("/")[-1].lower()

        # 1. Explicit Flags
        if any(x in token for x in ("outofstock", "soldout", "discontinued")):
            return False
        if any(x in token for x in ("instock", "available")):
            return True

        # 2. Date ranges (validFrom / validThrough)
        now = datetime.now(timezone.utc)
        vf = parse_iso_date(offer.get("validFrom") or self.raw.get("validFrom"))
        vt = parse_iso_date(
            offer.get("validThrough")
            or offer.get("priceValidUntil")
            or self.raw.get("validThrough")
        )

        if vf and now < vf:
            return False
        if vt and now > vt:
            return False

        # 3. Fallback: If there is a valid price, assume it is active.
        return bool(self.price and self.price > 0)


# ---------------------------------------------------------------------------
# Product Extractor & API
# ---------------------------------------------------------------------------
class ProductExtractor:
    """
    Orchestrates the extraction of product data from HTML content using
    schema normalization and heuristic selection.
    """
    def __init__(self):
        self.normalizer = SchemaNormalizer()

    def extract_from_html(self, html: str, url: str) -> ProductCandidate | None:
        # extruct extracts raw JSON-LD and Microdata
        data = extruct.extract(
            html, base_url=url, syntaxes=["json-ld", "microdata"], errors="ignore"
        )
        candidates = self.normalizer.collect_candidates(data)

        # Filter: Only keep objects where @type contains "product"
        products = [
            ProductCandidate(c)
            for c in candidates
            if any("product" in t for t in c.get("@type", []))
        ]
        if not products:
            return None

        # Heuristic: Pick the candidate with the most data (Title + Description + Offers)
        return max(
            products,
            key=lambda p: sum(bool(x) for x in (p.title, p.offers, p.description)),
        )


def extract_product(
    html_content: str,
    url: str,
    title: str | None = None,
    description: str | None = None,
    price: Any = None,
    currency: str | None = None,
    ean: str | None = None,
    mpn: str | None = None,
) -> Product | None:
    """
    Main entry point for extracting a Product object from HTML.
    Merges extracted data with optional manual overrides.
    """
    extractor = ProductExtractor()
    candidate = extractor.extract_from_html(html_content, url)

    # Defaults from extraction
    ext_price = candidate.price if candidate else None
    ext_curr = candidate.currency if candidate else None
    ext_ean = candidate.ean if candidate else None
    ext_mpn = candidate.mpn if candidate else None

    # Logic note: candidate.is_active relies on extracted data (including price).
    # If the user supplies a manual `price` override for an item with no
    # internal price, `candidate.is_active` might return False.
    # We patch that heuristic here.
    ext_active = candidate.is_active if candidate else False

    final_price = price or ext_price

    # If we have a final price but the candidate thought it was inactive
    # strictly due to missing price, force it active.
    if not ext_active and final_price and candidate and not ext_price:
        # Re-check active logic assuming price is valid
        ext_active = True

    # Merge extracted data with optional manual overrides
    data = {
        "url": url,
        "title": title or (candidate.title if candidate else None),
        "description": description or (candidate.description if candidate else None),
        "price": final_price,
        "currency": currency or ext_curr,
        "ean": ean or ext_ean,
        "mpn": mpn or ext_mpn,
        "is_active": ext_active,
    }

    try:
        return Product(**data)
    except (ValidationError, ValueError):
        return None
