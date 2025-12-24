import asyncio
import queue
from pathlib import Path

from crawlee import ConcurrencySettings, Request
from crawlee.crawlers import PlaywrightCrawler
from crawlee.proxy_configuration import ProxyConfiguration

from webstore_sleuth.schemas import DynamicSite, Product
from webstore_sleuth.webstore_sleuth_crawlee.router import LABEL_CATEGORY, build_router

BASE_DIR = Path(__file__).resolve().parent


class PlaywrightCrawlerRunner:
    """
    Manages Crawlee PlaywrightCrawler instances and their lifecycle.

    This version starts a separate PlaywrightCrawler per start URL.
    """

    def __init__(self, sites: list[DynamicSite], max_parallel_crawlers: int = 10):
        self.sites = sites
        self.max_parallel_crawlers = max_parallel_crawlers
        self.results_queue: queue.Queue = queue.Queue()

    async def _run_single_crawler(
        self,
        start_url: str,
        site_dict: dict,
        category_meta: dict,
        proxy_configuration: ProxyConfiguration | None,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:

            def on_product(product: Product) -> None:
                self.results_queue.put(product)

            router = build_router(on_product=on_product)

            # NOTE: This concurrency applies *within this single crawler* (i.e. for this one start URL).
            # If you run multiple crawlers concurrently, total parallelism becomes:
            #   max_parallel_crawlers * crawler.max_concurrency
            crawler = PlaywrightCrawler(
                request_handler=router,
                max_requests_per_crawl=None,
                headless=True,
                browser_type="firefox",
                concurrency_settings=ConcurrencySettings(
                    min_concurrency=3,
                    max_concurrency=10,
                ),
                proxy_configuration=proxy_configuration,
            )

            req = Request.from_url(
                url=start_url,
                unique_key=start_url,
                label=LABEL_CATEGORY,
                user_data={
                    "site_config": {"data": site_dict},
                    "category_meta": category_meta,
                    "page_num": 1,
                },
            )

            await crawler.run([req])

    async def _run_crawl(self) -> None:
        proxies_path = BASE_DIR.parent / "proxies.txt"
        proxy_urls: list[str] = []
        if proxies_path.exists():
            with proxies_path.open("r", encoding="utf-8") as f:
                proxy_urls = [line.strip() for line in f if line.strip()]

        proxy_configuration = ProxyConfiguration(proxy_urls=proxy_urls) if proxy_urls else None

        # One "job" per URL
        jobs: list[tuple[str, dict, dict]] = []
        for site in self.sites:
            site_dict = site.model_dump()
            for url, category_meta in site.category_urls.items():
                jobs.append((url, site_dict, category_meta))

        semaphore = asyncio.Semaphore(self.max_parallel_crawlers)

        tasks = [
            asyncio.create_task(
                self._run_single_crawler(
                    start_url=url,
                    site_dict=site_dict,
                    category_meta=category_meta,
                    proxy_configuration=proxy_configuration,
                    semaphore=semaphore,
                )
            )
            for (url, site_dict, category_meta) in jobs
        ]

        # If one crawler fails, we still want others to keep running.
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                # You can replace this with proper logging if you have a logger configured.
                print(f"[crawler] A per-URL crawler failed: {res!r}")

    def run(self) -> None:
        try:
            asyncio.run(self._run_crawl())
        except KeyboardInterrupt:
            pass
        finally:
            # Sentinel so consumers can stop.
            self.results_queue.put(None)