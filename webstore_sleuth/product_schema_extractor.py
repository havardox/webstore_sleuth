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
from webstore_sleuth.schema_org_extractor import SchemaOrgExtractor, SchemaOrgEntity

GTIN_KEYS = ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "ean", "isbn")


def get_first_nonempty(*args) -> str | None:
    for a in args:
        if isinstance(a, str) and a.strip():
            return a.strip()
        if isinstance(a, (int, float, Decimal)):
            return str(a)
    return None


class ProductCandidate:
    """
    Wraps a SchemaEntity.
    ASSUMPTION: All nested structured data are SchemaEntity objects, not dicts.
    """

    def __init__(self, entity: SchemaOrgEntity):
        self.entity = entity
        self.props = entity.properties

        # Filter offers: they are now guaranteed to be SchemaEntity if structured
        raw_offers = ensure_list(self.props.get("offers"))
        self.offers = [o for o in raw_offers if isinstance(o, SchemaOrgEntity)]

    @property
    def title(self) -> str | None:
        return get_first_nonempty(self.props.get("name"))

    @property
    def description(self) -> str | None:
        return get_first_nonempty(self.props.get("description"))

    @property
    def mpn(self) -> str | None:
        val = self.props.get("mpn")
        if val:
            return str(val)

        raw_identifiers = ensure_list(
            self.props.get("identifier") or self.props.get("additionalProperty")
        )

        # Iterate over SchemaEntities (identifiers are objects)
        for ident in raw_identifiers:
            if not isinstance(ident, SchemaOrgEntity):
                continue

            # Direct access to .properties
            pid = str(
                ident.properties.get("propertyID") or ident.properties.get("name") or ""
            ).lower()
            if pid in ("mpn", "manufacturer part number"):
                return str(ident.properties.get("value"))
        return None

    @property
    def best_offer(self) -> SchemaOrgEntity | None:
        """
        Returns the best Offer SchemaEntity, or None.
        """
        if not self.offers:
            return None

        def score(o: SchemaOrgEntity) -> tuple[int, int]:
            avail = str(o.properties.get("availability") or "").lower()
            avail_score = (
                0
                if "instock" in avail
                else (2 if any(x in avail for x in ("outofstock", "soldout")) else 1)
            )
            # Check for price existence in properties
            return avail_score, (0 if o.properties.get("price") else 1)

        return min(self.offers, key=score)

    @property
    def price(self) -> Decimal | None:
        offer = self.best_offer
        if not offer:
            return None

        # priceSpecification is now a SchemaEntity (if present)
        price_spec = offer.properties.get("priceSpecification")
        spec_price = (
            price_spec.properties.get("price")
            if isinstance(price_spec, SchemaOrgEntity)
            else None
        )

        raw_price = get_first_nonempty(offer.properties.get("price"), spec_price)
        return parse_price(raw_price)

    @property
    def currency(self) -> str | None:
        offer = self.best_offer
        if not offer:
            return None

        price_spec = offer.properties.get("priceSpecification")
        spec_curr = (
            price_spec.properties.get("priceCurrency")
            if isinstance(price_spec, SchemaOrgEntity)
            else None
        )

        return get_first_nonempty(offer.properties.get("priceCurrency"), spec_curr)

    @property
    def ean(self) -> str | None:
        # Check root props
        for k in GTIN_KEYS:
            if val := self.props.get(k):
                return str(val)

        # Check offer props
        if offer := self.best_offer:
            for k in GTIN_KEYS:
                if val := offer.properties.get(k):
                    return str(val)

        # Fallback: identifiers
        raw_identifiers = ensure_list(
            self.props.get("identifier") or self.props.get("additionalProperty")
        )
        for ident in raw_identifiers:
            if not isinstance(ident, SchemaOrgEntity):
                continue

            pid = str(
                ident.properties.get("propertyID") or ident.properties.get("name") or ""
            ).lower()
            if any(k in pid for k in ("gtin", "ean", "isbn")):
                return str(ident.properties.get("value"))
        return None

    @property
    def is_active(self) -> bool:
        offer = self.best_offer
        if not offer:
            # Fallback: if we found a price on the main product but no offers,
            # extraction might assume active if strict logic isn't applied.
            # But based on strict logic: no offer = unknown/inactive.
            return False

        token = str(offer.properties.get("availability") or "").split("/")[-1].lower()

        if any(x in token for x in ("outofstock", "soldout", "discontinued")):
            return False
        if any(x in token for x in ("instock", "available")):
            return True

        now = datetime.now(timezone.utc)
        vf = parse_iso_date(
            offer.properties.get("validFrom") or self.props.get("validFrom")
        )

        vt_source = (
            offer.properties.get("validThrough")
            or offer.properties.get("priceValidUntil")
            or self.props.get("validThrough")
        )
        vt = parse_iso_date(vt_source)

        if vf and now < vf:
            return False
        if vt and now > vt:
            return False

        return bool(self.price and self.price > 0)


# ---------------------------------------------------------------------------
# Product Extractor
# ---------------------------------------------------------------------------
class ProductExtractor:
    def __init__(self):
        self.normalizer = SchemaOrgExtractor()

    def extract_from_html(self, html: str, url: str) -> ProductCandidate | None:
        data = extruct.extract(
            html, base_url=url, syntaxes=["json-ld", "microdata"], errors="ignore"
        )
        candidates = self.normalizer.collect_candidates(data)

        # Filter entities where type includes "product"
        products = [
            ProductCandidate(c)
            for c in candidates
            if any("product" in t for t in c.types)
        ]

        if not products:
            return None

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
