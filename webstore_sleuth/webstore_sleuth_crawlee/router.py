
import hashlib
from collections.abc import Callable
from urllib.parse import urljoin

from crawlee import Request
from crawlee.crawlers import PlaywrightCrawlingContext
from crawlee.router import Router

from webstore_sleuth.product_schema_extractor import extract_product
from webstore_sleuth.schemas import DynamicSite, Product

LABEL_CATEGORY = "CATEGORY"
LABEL_PRODUCT = "PRODUCT"


def _as_xpath_selector(xpath: str) -> str:
    return xpath if xpath.startswith("xpath=") else f"xpath={xpath}"


async def _handle_cookie_consent(context: PlaywrightCrawlingContext, xpath: str | None) -> None:
    if not xpath:
        return

    selector = _as_xpath_selector(xpath)
    try:
        locator = context.page.locator(selector).first
        if await locator.is_visible(timeout=2000):
            context.log.info("Cookie consent banner detected. Clicking...")
            try:
                await locator.click(timeout=5000)
                await locator.wait_for(state="hidden", timeout=5000)
                context.log.info("Cookie consent banner dismissed and hidden.")
            except Exception as e:
                context.log.warning(f"Clicked cookie consent, but it refused to hide immediately: {e}")
    except Exception:
        return


async def _scroll_to_bottom(page) -> None:
    try:
        await page.evaluate(
            """
            async () => {
                await new Promise(resolve => {
                    let total = 0;
                    const distance = 200;
                    const timer = setInterval(() => {
                        const height = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        total += distance;
                        if (total >= height) {
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                });
            }
            """
        )
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        return


async def _enqueue_xpath(
    context: PlaywrightCrawlingContext,
    xpath: str,
    label: str,
    user_data: dict[str, object],
) -> None:
    if not xpath:
        return

    selector = _as_xpath_selector(xpath)
    try:
        hrefs: list[str | None] = await context.page.locator(selector).evaluate_all(
            "els => els.map(e => e.getAttribute('href'))"
        )

        requests: list[Request] = []
        for href in hrefs:
            if not href:
                continue
            full_url = urljoin(context.page.url, href)
            req = Request.from_url(full_url, label=label)
            req.user_data.update(user_data)
            requests.append(req)

        if requests:
            await context.add_requests(requests)
            context.log.info(f"Enqueued {len(requests)} {label} links")
    except Exception as e:
        context.log.error(f"Failed enqueue from xpath: {e}")


def _get_product_extractor_data(context: PlaywrightCrawlingContext) -> tuple[dict[str, object], dict[str, object]]:
    return (
        context.request.user_data["site_config"],  # type: ignore[index]
        context.request.user_data.get("category_meta", {}),  # type: ignore[return-value]
    )


def _get_current_site_model(site_data: dict[str, object]) -> DynamicSite:
    return DynamicSite(**site_data["data"])  # type: ignore[index]


async def _enqueue_next_category_request_via_click(
    context: PlaywrightCrawlingContext,
    site: DynamicSite,
    site_data: dict[str, object],
    category_meta: dict[str, object],
    current_page_num: int,
) -> None:
    if not (site.next_page_click and site.next_page_xpath):
        context.log.info("Pagination not configured or not click-based. Finishing.")
        return

    btn_selector = _as_xpath_selector(site.next_page_xpath)
    button = context.page.locator(btn_selector).first

    try:
        if not await button.is_visible(timeout=2000):
            context.log.info("No next page button visible. Category crawl complete.")
            return
    except Exception:
        context.log.info("No next page button visible (lookup failed). Category crawl complete.")
        return

    before_url = context.page.url

    await _handle_cookie_consent(context, site.cookies_consent_xpath)

    context.log.info(f"Next page available → Clicking to discover URL for page {current_page_num + 1}")
    await button.click(timeout=5000)

    # Works for SPA pushState updates too.
    await context.page.wait_for_function(
        "oldUrl => window.location.href !== oldUrl",
        arg=before_url,
        timeout=15000,
    )

    try:
        await context.page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    next_url = context.page.url
    if next_url == before_url:
        context.log.warning("Clicked Next, but URL did not change. Not enqueueing next page.")
        return

    next_req = Request.from_url(next_url, label=LABEL_CATEGORY)
    next_req.user_data.update(
        {
            "site_config": site_data,
            "category_meta": category_meta,
            "page_num": current_page_num + 1,
        }
    )

    await context.add_requests([next_req])
    context.log.info(f"Enqueued CATEGORY page #{current_page_num + 1} → {next_url}")


def build_router(on_product: Callable[[Product], None]) -> Router:
    """
    Builds a Router that emits Product objects via the provided callback.

    This avoids any non-existent "request finished callback" API and streams results
    from the PRODUCT handler directly into your application queue.
    """
    router = Router()

    @router.handler(LABEL_CATEGORY)
    async def category_handler(context: PlaywrightCrawlingContext) -> None:
        site_data, category_meta = _get_product_extractor_data(context)
        site = _get_current_site_model(site_data)

        current_page_num = int(context.request.user_data.get("page_num", 1))

        context.log.info(f"Processing CATEGORY page #{current_page_num} | URL: {context.page.url}")

        await _handle_cookie_consent(context, site.cookies_consent_xpath)

        await _enqueue_xpath(
            context=context,
            xpath=site.product_page_xpath,
            label=LABEL_PRODUCT,
            user_data={
                "site_config": site_data,
                "category_meta": category_meta,
            },
        )

        if site.infinite_scroll:
            await _scroll_to_bottom(context.page)
            await _handle_cookie_consent(context, site.cookies_consent_xpath)
            await _enqueue_xpath(
                context=context,
                xpath=site.product_page_xpath,
                label=LABEL_PRODUCT,
                user_data={
                    "site_config": site_data,
                    "category_meta": category_meta,
                },
            )

        # Enqueue next category page by clicking and using the resulting URL
        await _enqueue_next_category_request_via_click(
            context=context,
            site=site,
            site_data=site_data,
            category_meta=category_meta,
            current_page_num=current_page_num,
        )

    @router.handler(LABEL_PRODUCT)
    async def product_handler(context: PlaywrightCrawlingContext) -> None:
        site_data, category_meta = _get_product_extractor_data(context)
        site = _get_current_site_model(site_data)

        context.log.info(f"Scraping PRODUCT: {context.request.url}")
        await _handle_cookie_consent(context, site.cookies_consent_xpath)

        async def get_text(xpath: str | None) -> str | None:
            if not xpath:
                return None
            try:
                selector = _as_xpath_selector(xpath)
                return await context.page.locator(selector).first.inner_text(timeout=2000)
            except Exception:
                return None

        manual_fields = {
            "title": await get_text(site.title_xpath),
            "description": await get_text(site.description_xpath),
            "price": await get_text(site.price_xpath),
            "currency": await get_text(site.currency_xpath),
            "ean": await get_text(site.ean_xpath),
            "mpn": await get_text(site.mpn_xpath),
        }

        content = await context.page.content()
        product = extract_product(
            html_content=content,
            url=context.request.url,
            **manual_fields,
        )
        if not product:
            context.log.warning("No product extracted")
            return

        product.meta.update(category_meta)

        # Emit result immediately (your queue sink)
        on_product(product)

    @router.default_handler
    async def default_handler(context: PlaywrightCrawlingContext) -> None:
        context.log.warning(f"Unhandled request: {context.request.url} ({context.request.label})")

    return router