import logging
import scrapy
import re
from webstore_sleuth.schemas import BaseSite, BaseSite
from webstore_sleuth.product_schema_extractor import extract_product


class UniversalProductSpider(scrapy.Spider):
    name = "universal_product_spider"

    def __init__(self, sites: list[BaseSite], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sites = sites

    def start_requests(self):
        for site in self.sites:
            for url, category_meta in site.category_urls.items():
                if isinstance(site, BaseSite):
                    yield scrapy.Request(
                        url=url,
                        callback=self.parse_category,
                        meta={
                            "category_meta": category_meta,
                            "prev": None,
                            "site_config": site,
                        },
                    )
                else:
                    raise ValueError("Invalid Site type for ScrapyScraper")

    def parse_category(self, response):
        site: BaseSite = response.meta["site_config"]
        category_meta = response.meta["category_meta"]

        # Extracts links to individual product pages from the category listing
        product_links = self._extract_links(response, site.product_page_xpath)
        logging.info("This should appear")
        if not product_links:
            logging.info(f"No product links found on {response.url}")
            return

        for link in product_links:
            yield response.follow(
                link,
                callback=self.parse_product,
                meta={"site_config": site, "category_meta": category_meta},
            )

        # Extracts pagination links to the next category page
        next_links = self._extract_links(response, site.next_page_xpath)
        if not next_links:
            logging.debug(f"No pagination links found on {response.url}")
        else:
            yield response.follow(
                next_links[0],
                callback=self.parse_category,
                meta={
                    "site_config": site,
                    "category_meta": category_meta,
                    "prev": response.url,
                },
            )

    def parse_product(self, response):
        site: BaseSite = response.meta["site_config"]
        category_meta = response.meta.get("category_meta", {})

        # Extract fields using XPaths
        title = self._extract_xpath(response, site.title_xpath)
        description = self._extract_xpath(response, site.description_xpath)
        price = self._extract_xpath(response, site.price_xpath)
        currency = self._extract_xpath(response, site.currency_xpath)
        ean = self._extract_xpath(response, site.ean_xpath)
        mpn = self._extract_xpath(response, site.mpn_xpath)

        # Extracts a Product object or returns None if extraction fails
        product = extract_product(
            html_content=response.text,
            url=response.url,
            title=title,
            description=description,
            price=price,
            currency=currency,
            ean=ean,
            mpn=mpn,
        )

        if not product:
            self.logger.debug(f"No product data found for {response.url}")
            return

        # Scrapy expects a dict or Item, not a Pydantic object directly
        # (though some pipelines might handle it, standard practice is dict).
        # We also merge category metadata into the product metadata.

        product_dict = product.model_dump()
        product_dict["meta"].update(category_meta)

        yield product_dict

    def _extract_links(self, response, xpath: str) -> list[str]:
        """Extracts unique absolute URLs using the provided XPath."""
        if not xpath:
            return []

        sels = response.xpath(xpath)
        seen = set()
        uniq = []
        HREF_RE = re.compile(r'href=[\'"]([^\'"]+)[\'"]', re.IGNORECASE)

        for sel in sels:
            href = sel.xpath("./@href").get()
            url = None
            if href:
                url = response.urljoin(href.strip())
            else:
                txt = sel.get()
                if txt and ("<" in txt or ">" in txt):
                    m = HREF_RE.search(txt)
                    if m:
                        url = response.urljoin(m.group(1))
                else:
                    url = response.urljoin(txt)

            if url and url not in seen:
                seen.add(url)
                uniq.append(url)
        return uniq

    def _extract_xpath(self, response, xpath: str) -> str | None:
        """Extracts the first string value matching the XPath, or None."""
        if not xpath:
            return None
        value = response.xpath(xpath).get()
        return value if value else None
