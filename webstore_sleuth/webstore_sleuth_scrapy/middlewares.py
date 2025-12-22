import itertools
import random
import logging
import hashlib

from scrapy import Spider
from scrapy.http import Request
from scrapy.settings import Settings
from scrapy.exceptions import IgnoreRequest
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

        # Cartesian Product: Creates every possible combination of browser and proxy
        # We convert to a set of tuples for easier subtraction operations later
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
        # Respect standard Scrapy exclusion
        if request.meta.get("dont_impersonate"):
            return

        manual_impersonate = request.meta.get("impersonate")
        current_retry = request.meta.get("retry_times", 0)
        assigned_at = request.meta.get("_impersonate_assigned_at")

        # Initialize identity history
        history: list[dict] = request.meta.setdefault("_impersonate_history", [])

        # Skip if already assigned for this specific retry turn
        if assigned_at == current_retry:
            return

        # 1. Handle Manual Impersonation (Sticky for Retry 0)
        if manual_impersonate and "_impersonate_assigned_at" not in request.meta:
            request.meta["_impersonate_assigned_at"] = 0
            
            # Record the manual choice so it counts as "used" if it fails
            history.append({
                "browser": manual_impersonate,
                "proxy": request.meta.get("proxy"),
            })

            self._set_cookie_jar(
                request, manual_impersonate, request.meta.get("proxy")
            )
            return

        # 2. Determine Used Identities from History
        # We create a set of tuples (browser, proxy) from the history list
        used_identities = {
            (item["browser"], item["proxy"]) 
            for item in history
        }

        # 3. Calculate Available Candidates (Pool - Used)
        # Works for both proxy scenarios and local-only (proxy=None) scenarios
        available_candidates = [
            identity for identity in self.pool 
            if identity not in used_identities
        ]

        # 4. Abort if exhausted
        if not available_candidates:
            logger.error(
                f"Url: {request.url} | "
                f"Exhausted all {len(self.pool)} browser/proxy combinations after "
                f"{current_retry} retries. Aborting request."
            )
            raise IgnoreRequest("Exhausted all impersonation identities.")

        # 5. Select new identity
        browser, proxy = random.choice(available_candidates)

        logger.debug(
            f"Url: {request.url} | Retry: {current_retry} | "
            f"Assigning: {browser} | Proxy: {proxy}"
        )

        request.meta["impersonate"] = browser
        request.meta["_impersonate_assigned_at"] = current_retry

        # Record identity usage
        history.append({
            "browser": browser,
            "proxy": proxy,
        })

        # Proxy handling
        if not request.meta.get("dont_proxy"):
            if proxy:
                request.meta["proxy"] = proxy
            elif "proxy" in request.meta:
                # If we switched to a local identity (proxy=None), ensure we clean up old proxy meta
                del request.meta["proxy"]

        # Cookie isolation
        self._set_cookie_jar(request, browser, proxy)

    def _set_cookie_jar(
        self, request: Request, browser: str, proxy: str | None
    ) -> None:
        """
        Calculates a deterministic cookie jar ID based on the identity pair.
        Ensures cookies never leak across browser/proxy combinations.
        """
        if self.cookies_enabled and not request.meta.get("cookiejar"):
            pair_id = f"{browser}|{proxy or 'local'}"
            jar_id = hashlib.md5(pair_id.encode("utf-8")).hexdigest()[:12]
            request.meta["cookiejar"] = jar_id