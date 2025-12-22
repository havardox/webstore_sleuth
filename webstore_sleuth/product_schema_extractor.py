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
from webstore_sleuth.product_schema_normalizer import (
    SchemaNormalizer, 
    SchemaEntity
)

GTIN_KEYS = ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "ean", "isbn")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_first_nonempty(*args) -> str | None:
    """
    Returns the first non-empty string from the arguments.
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
    Wraps a SchemaEntity to provide heuristic extraction methods.
    Handles the discrepancy between JSON-LD (nested dicts) and Microdata
    (nested SchemaEntities) via the _unwrap helper.
    """

    def __init__(self, entity: SchemaEntity):
        self.entity = entity
        self.props = entity.properties  # Shortcut to the data payload
        
        # Normalize offers list: unwrap SchemaEntities back to dicts for uniform handling
        raw_offers = ensure_list(self.props.get("offers"))
        self.offers = [
            self._unwrap(o) for o in raw_offers if isinstance(o, (dict, SchemaEntity))
        ]

    @staticmethod
    def _unwrap(item: Any) -> dict[str, Any]:
        """
        Helper to extract the dictionary payload from a nested item, 
        whether it is a raw dict or a SchemaEntity.
        """
        if isinstance(item, SchemaEntity):
            return item.properties
        return item if isinstance(item, dict) else {}

    @property
    def title(self) -> str | None:
        return get_first_nonempty(self.props.get("name"))

    @property
    def description(self) -> str | None:
        return get_first_nonempty(self.props.get("description"))

    @property
    def mpn(self) -> str | None:
        """
        Locates the Manufacturer Part Number (MPN).
        """
        # Check explicit field first
        val = self.props.get("mpn")
        if val:
            return str(val)

        # Fallback: generic "identifier" list.
        # Handle potential nested SchemaEntities in the identifier list
        raw_identifiers = ensure_list(
            self.props.get("identifier") or self.props.get("additionalProperty")
        )
        
        for item in raw_identifiers:
            ident = self._unwrap(item)
            if not ident: 
                continue

            pid = str(ident.get("propertyID") or ident.get("name") or "").lower()
            if pid in ("mpn", "manufacturer part number"):
                return str(ident.get("value"))
        return None

    @property
    def best_offer(self) -> dict[str, Any]:
        """
        Selects the single most relevant offer from the list of offers.
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
            # Prefer offers that actually have a price (0) over those that don't (1)
            return avail_score, (0 if o.get("price") else 1)

        return min(self.offers, key=score)

    @property
    def price(self) -> Decimal | None:
        """
        Extracts the numeric price from the best available offer.
        """
        offer = self.best_offer
        # Handle priceSpecification if it is a nested object/entity
        price_spec = self._unwrap(offer.get("priceSpecification"))

        raw_price = get_first_nonempty(offer.get("price"), price_spec.get("price"))
        return parse_price(raw_price)

    @property
    def currency(self) -> str | None:
        offer = self.best_offer
        price_spec = self._unwrap(offer.get("priceSpecification"))
        return get_first_nonempty(
            offer.get("priceCurrency"), price_spec.get("priceCurrency")
        )

    @property
    def ean(self) -> str | None:
        """
        Searches for a Global Trade Item Number (GTIN/EAN/ISBN).
        """
        # Search for GTINs in the product root AND the selected offer
        sources = [self.props] + ([self.best_offer] if self.offers else [])
        for source in sources:
            for k in GTIN_KEYS:
                if val := source.get(k):
                    return str(val)

        # Fallback: Check generic identifiers
        raw_identifiers = ensure_list(
            self.props.get("identifier") or self.props.get("additionalProperty")
        )
        for item in raw_identifiers:
            ident = self._unwrap(item)
            if not ident:
                continue

            pid = str(ident.get("propertyID") or ident.get("name") or "").lower()
            if any(k in pid for k in ("gtin", "ean", "isbn")):
                return str(ident.get("value"))
        return None

    @property
    def is_active(self) -> bool:
        """
        Determines if the product is currently buyable.
        """
        offer = self.best_offer
        token = str(offer.get("availability") or "").split("/")[-1].lower()

        # 1. Explicit Flags
        if any(x in token for x in ("outofstock", "soldout", "discontinued")):
            return False
        if any(x in token for x in ("instock", "available")):
            return True

        # 2. Date ranges
        now = datetime.now(timezone.utc)
        vf = parse_iso_date(offer.get("validFrom") or self.props.get("validFrom"))
        
        # 'validThrough' might be in offer, price spec, or root
        vt_source = offer.get("validThrough") or offer.get("priceValidUntil") or self.props.get("validThrough")
        vt = parse_iso_date(vt_source)

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
    Orchestrates the extraction of product data using SchemaEntity.
    """
    def __init__(self):
        self.normalizer = SchemaNormalizer()

    def extract_from_html(self, html: str, url: str) -> ProductCandidate | None:
        data = extruct.extract(
            html, base_url=url, syntaxes=["json-ld", "microdata"], errors="ignore"
        )
        
        # Returns list[SchemaEntity]
        candidates = self.normalizer.collect_candidates(data)

        # Filter: Only keep entities where types contain "product"
        products = [
            ProductCandidate(entity)
            for entity in candidates
            if any("product" in t for t in entity.types)
        ]
        
        if not products:
            return None

        # Heuristic: Pick the candidate with the most data
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
    """
    extractor = ProductExtractor()
    candidate = extractor.extract_from_html(html_content, url)

    ext_price = candidate.price if candidate else None
    ext_curr = candidate.currency if candidate else None
    ext_ean = candidate.ean if candidate else None
    ext_mpn = candidate.mpn if candidate else None
    ext_active = candidate.is_active if candidate else False

    final_price = price or ext_price

    if not ext_active and final_price and candidate and not ext_price:
        ext_active = True

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