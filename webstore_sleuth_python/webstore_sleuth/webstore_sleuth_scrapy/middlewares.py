import itertools
import random
import logging
import hashlib

from scrapy import Spider
from scrapy.http import Request
from scrapy.settings import Settings
from curl_cffi.requests import BrowserType

logger = logging.getLogger(__name__)


class ScrapyImpersonateSessionMiddleware:
    def __init__(self, settings: Settings):
        # List of proxies (or None for local)
        self.proxies: list[str | None] = settings.getlist("PROXIES") or []
        self.cookies_enabled: bool = settings.getbool("COOKIES_ENABLED", True)

        # Allow user to restrict specific browsers in settings, default to all
        allowed_browsers = settings.getlist("IMPERSONATE_BROWSERS", [])
        if allowed_browsers:
            self.browsers: list[str] = [b for b in BrowserType if b in allowed_browsers]
        else:
            self.browsers: list[str] = list(BrowserType)

        if not self.browsers:
            raise ValueError("No valid browsers found for impersonation.")

        # Specific handling for no proxies (local execution)
        if not self.proxies:
            self.proxies = [None]

        # 1. Cartesian Product: Create every possible combination
        # This maximizes the entropy of your scraper fingerprints.
        self.pool: list[tuple[str, str | None]] = list(
            itertools.product(self.browsers, self.proxies)
        )

        logger.info(
            f"Initialized ScrapyImpersonateSessionMiddleware with {len(self.pool)} "
            f"identities (Browsers: {len(self.browsers)} x Proxies: {len(self.proxies)})"
        )

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def process_request(self, request: Request, spider: Spider) -> None:
        # 1. Respect standard Scrapy exclusion
        if request.meta.get("dont_impersonate"):
            return

        # 2. Check for manual overrides or sticky retry sessions
        # If the user manually set a browser in the spider, we respect it
        # UNLESS this is a retry where we need to rotate to a new identity.
        manual_impersonate = request.meta.get("impersonate")
        current_retry = request.meta.get("retry_times", 0)
        assigned_at = request.meta.get("_impersonate_assigned_at")

        # If assigned this turn, or manually set by user (and not a retry rotation), skip.
        if assigned_at == current_retry:
            return
        if manual_impersonate and "_impersonate_assigned_at" not in request.meta:
            # User set it manually in start_requests, treat as sticky for run 0
            request.meta["_impersonate_assigned_at"] = 0
            self._set_cookie_jar(request, manual_impersonate, request.meta.get("proxy"))
            return

        # 3. Intelligent Selection
        candidates = self.pool

        # Filtering logic on retry
        if current_retry > 0:
            prev_browser = request.meta.get("impersonate")
            prev_proxy = request.meta.get("proxy")

            # Exclude the exact pair that failed
            filtered = [p for p in self.pool if p != (prev_browser, prev_proxy)]

            if filtered:
                candidates = filtered
                logger.debug(
                    f"Retry {current_retry} for {request.url}: Rotating identity. "
                    f"Dropped ({prev_browser}, {prev_proxy})"
                )
            else:
                logger.warning("No alternative identities available for retry.")

        # 4. Selection & Assignment
        browser, proxy = random.choice(candidates)

        request.meta["impersonate"] = browser
        request.meta["_impersonate_assigned_at"] = current_retry

        # Proxy Handling
        # Respect dont_proxy standard if set, otherwise apply proxy
        if not request.meta.get("dont_proxy"):
            if proxy:
                request.meta["proxy"] = proxy
            elif "proxy" in request.meta:
                # Clean up if we switched from a proxy-identity to a local-identity
                del request.meta["proxy"]

        # 5. Cookie Jar (Session Isolation)
        self._set_cookie_jar(request, browser, proxy)

    def _set_cookie_jar(
        self, request: Request, browser: str, proxy: str | None
    ) -> None:
        """
        Calculates a deterministic cookie jar ID based on the identity pair.
        This ensures that cookies acquired by 'Chrome v110 on Proxy A' are never
        leaked to 'Safari on Proxy B'.
        """
        if self.cookies_enabled and not request.meta.get("cookiejar"):
            # We use a hash to keep the meta key clean and short
            pair_id = f"{browser}|{proxy or 'local'}"
            jar_id = hashlib.md5(pair_id.encode("utf-8")).hexdigest()[:12]
            request.meta["cookiejar"] = jar_id
