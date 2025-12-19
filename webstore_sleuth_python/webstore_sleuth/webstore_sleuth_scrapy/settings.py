# Scrapy settings for webstore_sleuth_scrapy project
#
# For simplicity, this file contains only settings considered important or
# commonly used. You can find more settings consulting the documentation:
#
#     https://docs.scrapy.org/en/latest/topics/settings.html
#     https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
#     https://docs.scrapy.org/en/latest/topics/spider-middleware.html

import os

BOT_NAME = "webstore_sleuth_scrapy"

SPIDER_MODULES = ["webstore_sleuth_scrapy.spiders"]
NEWSPIDER_MODULE = "webstore_sleuth_scrapy.spiders"
CONCURRENT_REQUESTS = 1000
ADDONS = {
    "scrapoxy.Addon": 100,
}

SCRAPOXY_MASTER = os.getenv("SCRAPOXY_MASTER")
SCRAPOXY_API = os.getenv("SCRAPOXY_API")
SCRAPOXY_USERNAME = os.getenv("SCRAPOXY_USERNAME")
SCRAPOXY_PASSWORD = os.getenv("SCRAPOXY_PASSWORD")

SCRAPOXY_WAIT_FOR_PROXIES = True
SCRAPOXY_MODE_START = 'HOT'
SCRAPOXY_MODE_RESTART = 'HOT'
SCRAPOXY_MODE_STOP = 'OFF'
SCRAPOXY_PROXIES_CHECK = 20  # Default is 10 seconds

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

DOWNLOAD_HANDLERS = {
    "http": "scrapy_impersonate.ImpersonateDownloadHandler",
    "https": "scrapy_impersonate.ImpersonateDownloadHandler",
}

DOWNLOADER_MIDDLEWARES = {
    "scrapy_impersonate.RandomBrowserMiddleware": 1,
}

USER_AGENT = None

# Crawl responsibly by identifying yourself (and your website) on the user-agent
# USER_AGENT = "webstore_sleuth_scrapy (+http://www.yourdomain.com)"

# Obey robots.txt rules
ROBOTSTXT_OBEY = False


# Disable cookies (enabled by default)
COOKIES_ENABLED = False

# Disable Telnet Console (enabled by default)
TELNETCONSOLE_ENABLED = False

# Override the default request headers:
# DEFAULT_REQUEST_HEADERS = {
#    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
#    "Accept-Language": "en",
# }

# Enable or disable spider middlewares
# See https://docs.scrapy.org/en/latest/topics/spider-middleware.html
# SPIDER_MIDDLEWARES = {
#    "webstore_sleuth_scrapy.middlewares.WebstoreSleuthScrapySpiderMiddleware": 543,
# }

# Enable or disable downloader middlewares
# See https://docs.scrapy.org/en/latest/topics/downloader-middleware.html
# DOWNLOADER_MIDDLEWARES = {
#    "webstore_sleuth_scrapy.middlewares.WebstoreSleuthScrapyDownloaderMiddleware": 543,
# }

# Configure item pipelines
# See https://docs.scrapy.org/en/latest/topics/item-pipeline.html
# ITEM_PIPELINES = {
#     "webstore_sleuth_scrapy.pipelines.WebstoreSleuthScrapyPipeline": 300,
# }

# Enable and configure the AutoThrottle extension (disabled by default)
# See https://docs.scrapy.org/en/latest/topics/autothrottle.html
AUTOTHROTTLE_ENABLED = True
# The initial download delay
AUTOTHROTTLE_START_DELAY = 5
# The maximum download delay to be set in case of high latencies
AUTOTHROTTLE_MAX_DELAY = 60
# The average number of requests Scrapy should be sending in parallel to
# each remote server
AUTOTHROTTLE_TARGET_CONCURRENCY = 3
# Enable showing throttling stats for every response received:
AUTOTHROTTLE_DEBUG = False

URLLENGTH_LIMIT=4096

# Enable and configure HTTP caching (disabled by default)
# See https://dvocs.scrapy.org/en/latest/topics/downloader-middleware.html#httpcache-middleware-settings
# HTTPCACHE_ENABLED = True
# HTTPCACHE_EXPIRATION_SECS = 0
# HTTPCACHE_DIR = "httpcache"
# HTTPCACHE_IGNORE_HTTP_CODES = []
# HTTPCACHE_STORAGE = "scrapy.extensions.httpcache.FilesystemCacheStorage"

# Set settings whose default value is deprecated to a future-proof value
FEED_EXPORT_ENCODING = "utf-8"
