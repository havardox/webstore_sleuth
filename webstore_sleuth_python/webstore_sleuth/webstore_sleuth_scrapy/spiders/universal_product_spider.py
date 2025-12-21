import logging
import scrapy
import re
import os
from urllib.parse import urlparse
from webstore_sleuth.schemas import BaseSite, StaticSite
from webstore_sleuth.product_schema_extractor import extract_product


class UniversalProductSpider(scrapy.Spider):
    name = "universal_product_spider"

    def __init__(self, sites: list[StaticSite], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sites = sites
        # Stores the current file count for each domain
        # e.g., {'example.com': 5}
        self.domain_counts = {}

    def start_requests(self):
        for site in self.sites:
            for url, category_meta in site.category_urls.items():
                if isinstance(site, StaticSite):
                    yield scrapy.Request(
                        url=url,
                        callback=self.parse_category,
                        meta={
                            "category_meta": category_meta,
                            "prev": None,  # Indicates this is the first page
                            "site_config": site,
                        },
                    )
                else:
                    raise ValueError("Invalid Site type for ScrapyScraper")

    def parse_category(self, response):
        site: StaticSite = response.meta["site_config"]
        category_meta = response.meta["category_meta"]

        # 1. Extract links to individual product pages from the category listing
        product_links = self._extract_links(response, site.product_page_xpath)
        logging.info("This should appear")

        if not product_links:
            logging.info(f"No product links found on {response.url}")

            # CHECK: Only save debug HTML if this is the first page of the category
            # (prev is None implies it's the start request for this category)
            if response.meta.get("prev") is None:
                self._save_debug_html(response)
            return

        for link in product_links:
            yield response.follow(
                link,
                callback=self.parse_product,
                meta={"site_config": site, "category_meta": category_meta},
            )

        # 2. Extract pagination links to next category page
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

        # Now returns Product | None
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

        product_dict = product.model_dump()
        product_dict["meta"].update(category_meta)

        yield product_dict

    def _save_debug_html(self, response):
        """
        Saves the response body to debug/domain_N.html.
        Calculates N based on existing files in the folder to persist counts across runs.
        """
        try:
            folder = "debug"
            os.makedirs(folder, exist_ok=True)

            domain = urlparse(response.url).netloc

            # Determine the next number (N) for this domain
            next_n = self._get_next_file_number(folder, domain)

            # Construct filename: debug/domain_N.html
            filename = os.path.join(folder, f"{domain}_{next_n}.html")

            with open(filename, "wb") as f:
                f.write(response.body)

            self.logger.info(f"Saved debug HTML (First Page No Results) to {filename}")

        except Exception as e:
            self.logger.error(f"Failed to save debug HTML: {e}")

    def _get_next_file_number(self, folder: str, domain: str) -> int:
        """
        Returns the next available number N for domain_N.
        Checks the filesystem first if the domain hasn't been seen in this run yet.
        """
        # If we are already tracking this domain in memory, just increment
        if domain in self.domain_counts:
            self.domain_counts[domain] += 1
            return self.domain_counts[domain]

        # Otherwise, scan the debug folder to find the highest existing N
        max_n = 0
        prefix = f"{domain}_"

        try:
            # List all files in debug folder
            for fname in os.listdir(folder):
                if fname.startswith(prefix):
                    # Extract the part after "domain_"
                    suffix = fname[len(prefix) :]

                    # Remove extension (e.g., .html) to get the number
                    if "." in suffix:
                        number_part = suffix.split(".")[0]
                    else:
                        number_part = suffix

                    if number_part.isdigit():
                        n = int(number_part)
                        if n > max_n:
                            max_n = n
        except FileNotFoundError:
            # Folder doesn't exist yet, start at 0
            pass

        # Start at max_found + 1
        current_n = max_n + 1
        self.domain_counts[domain] = current_n
        return current_n

    def _extract_links(self, response, xpath: str) -> list[str]:
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
        if not xpath:
            return None
        value = response.xpath(xpath).get()
        return value if value else None
