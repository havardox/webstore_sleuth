from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, Annotated

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    StringConstraints,
    ConfigDict,
    model_validator,
)

from webstore_sleuth.utils.converters import parse_price

# Enforces stripped strings to ensure clean data
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

    # Uses UTC for system timestamps
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    meta: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("price", mode="before")
    @classmethod
    def validate_price(cls, v: Any) -> Decimal | None:
        return parse_price(v)


class BaseSite(BaseModel):
    category_urls: Dict[str, Dict[str, Any]]
    product_page_xpath: StrippedString

    # Optional selectors
    title_xpath: StrippedString | None = None
    description_xpath: StrippedString | None = None
    price_xpath: StrippedString | None = None
    currency_xpath: StrippedString | None = None
    ean_xpath: StrippedString | None = None
    mpn_xpath: StrippedString | None = None
    is_active_xpath: StrippedString | None = None
    
    # Interaction selectors
    cookies_consent_xpath: StrippedString | None = None

    # Used for both "Link href" (Static) and "Button selector" (Dynamic)
    next_page_xpath: StrippedString | None = None

    model_config = ConfigDict(frozen=True, extra="forbid")


class DynamicSite(BaseSite):
    """
    Site requiring browser interaction (Click or Scroll).

    attributes:
        next_page_click (bool): If True, 'next_page_xpath' is treated as a button to click.
        infinite_scroll (bool): If True, the page is scrolled until no new content loads.
    """

    next_page_click: bool = False
    infinite_scroll: bool = False

    @model_validator(mode="after")
    def validate_exclusivity(self) -> "DynamicSite":
        if self.next_page_click and self.infinite_scroll:
            raise ValueError(
                "A site cannot be both 'next_page_click' and 'infinite_scroll' at the same time."
            )
        return self