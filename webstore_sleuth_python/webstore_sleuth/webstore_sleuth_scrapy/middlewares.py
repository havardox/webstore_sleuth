import itertools
import random
import logging
import hashlib

from curl_cffi.requests import BrowserType

logger = logging.getLogger(__name__)


class ScrapyImpersonateSessionMiddleware:
    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def __init__(self, settings):
        self.proxies = list(settings.getlist("PROXIES"))
        self.browsers = list(BrowserType)
        self.cookies_enabled = settings.getbool("COOKIES_ENABLED", True)

        if not self.browsers:
            raise ValueError("BROWSERS setting is empty.")

        if not self.proxies:
            self.proxies = [None]

        # 1. Allocate Pairs
        # self.pool is a list of tuples: [(BrowserType.chrome, 'http://...'), ...]
        if len(self.browsers) >= len(self.proxies):
            self.pool = list(zip(self.browsers, itertools.cycle(self.proxies)))
        else:
            self.pool = list(zip(itertools.cycle(self.browsers), self.proxies))

        logger.info(f"Initialized with {len(self.pool)} unique browser/proxy pairs.")

    def process_request(self, request, spider):
        # 1. Skip if manually set (and not part of a middleware retry loop)
        if "impersonate" in request.meta and "_assigned_at_retry" not in request.meta:
            return

        # 2. Retry Logic
        current_retry = request.meta.get("retry_times", 0)
        last_assigned_at = request.meta.get("_assigned_at_retry")

        # If we assigned a pair for THIS retry attempt already, keep it sticky.
        if last_assigned_at is not None and last_assigned_at == current_retry:
            return

        # 3. Intelligent Selection
        candidates = self.pool

        # If this is a retry (current_retry > 0), we want to ensure we don't pick
        # the same pair that just failed.
        if current_retry > 0:
            previous_browser = request.meta.get("impersonate")
            previous_proxy = request.meta.get("proxy")

            # Filter the pool to exclude the pair that matches the previous request
            # We compare the tuple (browser, proxy)
            candidates = [
                pair for pair in self.pool if pair != (previous_browser, previous_proxy)
            ]

            # Edge Case: If the pool only has 1 item, candidates will be empty.
            # In that case, we must revert to the full pool (we can't switch).
            if not candidates:
                logger.warning(
                    "Only 1 proxy/browser pair available. Cannot switch on retry."
                )
                candidates = self.pool
            else:
                logger.debug(
                    f"Retry {current_retry}: Excluding failed pair ({previous_browser}, {previous_proxy})"
                )

        # 4. Pick from the filtered candidates
        browser, proxy = random.choice(candidates)

        request.meta["impersonate"] = browser

        if proxy:
            request.meta["proxy"] = proxy
        elif "proxy" in request.meta:
            # If we picked a pair with None proxy, but a proxy key exists from previous run, remove it
            del request.meta["proxy"]

        # 5. Cookie Jar (Session)
        if self.cookies_enabled:
            pair_id = f"{browser}|{str(proxy)}"
            request.meta["cookiejar"] = hashlib.md5(pair_id.encode()).hexdigest()[:10]

        # 6. Lock this identity to this specific retry attempt
        request.meta["_assigned_at_retry"] = current_retry
