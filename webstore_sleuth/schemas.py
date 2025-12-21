from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Annotated

from pydantic import BaseModel, Field, field_validator, StringConstraints, ConfigDict

from webstore_sleuth.utils.converters import parse_price

# Enforce stripped strings to avoid database pollution
StrippedString = Annotated[str, StringConstraints(strip_whitespace=True)]


class Product(BaseModel):
    url: StrippedString
    title: StrippedString
    description: StrippedString | None = None
    price: Decimal | None = None
    currency: StrippedString | None = None
    ean: StrippedString | None = None
    mpn: StrippedString | None = None
    is_active: bool | None = None

    # Always use UTC for system timestamps
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    meta: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("price", mode="before")
    @classmethod
    def validate_price(cls, v: Any) -> Decimal | None:
        # parse_price now returns None safely on failure
        return parse_price(v)


class BaseSite(BaseModel):
    category_urls: Dict[str, Dict[str, Any]]
    product_page_xpath: StrippedString
    title_xpath: StrippedString | None = None
    description_xpath: StrippedString | None = None
    price_xpath: StrippedString | None = None
    price_xpath: StrippedString | None = None
    currency_xpath: StrippedString | None = None
    ean_xpath: StrippedString | None = None
    mpn_xpath: StrippedString | None = None
    is_active_xpath: StrippedString | None = None

    model_config = ConfigDict(frozen=True, extra="forbid")


class StaticSite(BaseSite):
    next_page_xpath: StrippedString
