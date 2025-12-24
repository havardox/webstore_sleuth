import threading
from typing import Sequence, Iterator, List

from webstore_sleuth.schemas import BaseSite, DynamicSite, Product
from webstore_sleuth.scraper import Scraper
from .crawler import PlaywrightCrawlerRunner


class CrawleeScraper(Scraper):
    def __init__(self, sites: Sequence[BaseSite]):
        self.sites: List[DynamicSite] = []
        for site in sites:
            if not isinstance(site, DynamicSite):
                raise ValueError(
                    f"CrawleeScraper only supports DynamicSite. Got {type(site).__name__}."
                )
            self.sites.append(site)

        self._crawler_runner = PlaywrightCrawlerRunner(sites=self.sites)

    def crawl(self) -> Iterator[Product]:
        t = threading.Thread(target=self._crawler_runner.run, daemon=True)
        t.start()

        while True:
            item = self._crawler_runner._results_queue.get()
            if item is None:
                break
            yield item

        t.join()