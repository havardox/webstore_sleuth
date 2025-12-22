"""
Defines the Scraper protocol and generic crawling utilities.
"""
from typing import Protocol, Iterator, Iterable, Sequence
from webstore_sleuth.schemas import Product, BaseSite


class Scraper(Protocol):
    """
    Protocol definition for any scraping backend (Scrapy, Selenium, etc).
    """

    sites: Sequence[BaseSite]

    def crawl(self) -> Iterator[Product]:
        """
        Generator that runs the crawl and yields standardized Product objects.
        """
        ...


def crawl_all(scrapers: Iterable[Scraper]) -> Iterator[Product]:
    """
    Generic entry point to run multiple scraper instances sequentially
    and yield their combined results.
    """
    for scraper in scrapers:
        yield from scraper.crawl()
