import queue
import threading
from typing import Sequence, Iterator, Any
from scrapy.crawler import CrawlerProcess
from scrapy import signals
from scrapy.utils.project import get_project_settings

from webstore_sleuth.schemas import Product, BaseSite
from webstore_sleuth.scraper import Scraper
from webstore_sleuth.webstore_sleuth_scrapy.spiders.universal_product_spider import (
    UniversalProductSpider,
)


class ScrapyScraper(Scraper):
    """
    Concrete implementation of the Scraper protocol using Scrapy.
    """

    def __init__(self, sites: Sequence[BaseSite]):
        self.sites = sites
        self._results_queue = queue.Queue()
        self._settings = get_project_settings()

    def crawl(self) -> Iterator[Product]:
        t = threading.Thread(target=self._run_process)
        t.start()

        while True:
            item = self._results_queue.get()
            if item is None:
                break

            yield self._to_product(item)

        t.join()

    def _run_process(self):
        process = CrawlerProcess(self._settings, install_root_handler=False)

        crawler = process.create_crawler(UniversalProductSpider)
        crawler.signals.connect(self._on_item_scraped, signal=signals.item_scraped)
        process.crawl(crawler, sites=self.sites)

        # Explicitly disables signal handlers to prevent threading errors
        process.start(install_signal_handlers=False)

        self._results_queue.put(None)

    def _on_item_scraped(self, item, response, spider):
        self._results_queue.put(item)

    def _to_product(self, item: Any) -> Product:
        # Converts the item (dict) from the spider into a Product object
        if isinstance(item, dict):
            return Product(**item)
        if isinstance(item, Product):
            return item
        raise ValueError(f"Unknown item type: {type(item)}")
