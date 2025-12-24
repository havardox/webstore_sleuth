import asyncio

from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext


async def main() -> None:
    # The browserforge fingerprints and headers are used by default.
    crawler = PlaywrightCrawler(
        browser_launch_options={
            "args": ["--no-sandbox", "--disable-setuid-sandbox"],
        },
        headless=True,
        browser_type='firefox'
    )

    @crawler.router.default_handler
    async def handler(context: PlaywrightCrawlingContext) -> None:
        url = context.request.url
        context.log.info(f"Crawling URL: {url}")

        # Decode and log the response body, which contains the headers we sent.
        headers = (await context.response.body()).decode()
        context.log.info(f"Response headers: {headers}")

        # Extract and log the User-Agent and UA data used in the browser context.
        ua = await context.page.evaluate("() => window.navigator.userAgent")
        ua_data = await context.page.evaluate("() => window.navigator.userAgentData")
        context.log.info(f"Navigator user-agent: {ua}")
        context.log.info(f"Navigator user-agent data: {ua_data}")

    # The endpoint httpbin.org/headers returns the request headers in the response body.
    await crawler.run(["https://www.httpbin.org/headers"])


if __name__ == "__main__":
    asyncio.run(main())
