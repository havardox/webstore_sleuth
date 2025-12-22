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

        # Optimization Flag: Determines if IP rotation is possible based on proxy count
        self.has_multiple_proxies = len(self.proxies) > 1

        # Cartesian Product: Creates every possible combination of browser and proxy
        # to maximize the entropy of scraper fingerprints.
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
        # Respects standard Scrapy exclusion
        if request.meta.get("dont_impersonate"):
            return

        # Checks for manual overrides or sticky retry sessions
        # Respects manually set browser in the spider,
        # unless this is a retry where rotation to a new identity is required.
        manual_impersonate = request.meta.get("impersonate")
        current_retry = request.meta.get("retry_times", 0)
        assigned_at = request.meta.get("_impersonate_assigned_at")

        # Skips if assigned this turn or manually set (unless rotating for retry).
        if assigned_at == current_retry:
            return

        # If user set it manually in start_requests, treat as sticky for run 0
        if manual_impersonate and "_impersonate_assigned_at" not in request.meta:
            request.meta["_impersonate_assigned_at"] = 0
            self._set_cookie_jar(request, manual_impersonate, request.meta.get("proxy"))
            return

        # Selects an identity based on retry logic
        candidates = self.pool

        # Filtering logic on retry
        if current_retry > 0:
            prev_proxy = request.meta.get("proxy")
            prev_browser = request.meta.get("impersonate")

            if self.has_multiple_proxies:
                # Strategy A: Forces IP Rotation
                # If multiple proxies are available, priority is to change the IP address.
                # The browser is selected randomly.
                candidates = [p for p in self.pool if p[1] != prev_proxy]
                logger.debug(f"Retry {current_retry}: Rotating Proxy (IP change).")
            else:
                # Strategy B: Forces Browser Rotation
                # If Local or only 1 Proxy, changes the TLS fingerprint/Browser.
                candidates = [p for p in self.pool if p[0] != prev_browser]
                logger.debug(f"Retry {current_retry}: Rotating Browser (IP locked).")

            # Failsafe: If filtering left us empty (shouldn't happen unless config is tiny),
            # revert to full pool to keep the request alive.
            if not candidates:
                logger.warning(
                    "No alternative identities available for retry. Reusing pool."
                )
                candidates = self.pool

        # Selects and assigns the identity
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

        # Sets the Cookie Jar for session isolation
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
