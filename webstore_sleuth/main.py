from webstore_sleuth.schemas import BaseSite, DynamicSite
from webstore_sleuth.scraper import crawl_all
from webstore_sleuth.webstore_sleuth_crawlee.impl import CrawleeScraper
from webstore_sleuth.webstore_sleuth_scrapy.impl import ScrapyScraper

import logging


def main():
    # Configures logging to output info level logs
    logging.basicConfig(
        level=logging.INFO,
    )

    # Initializes the logger for the current module
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    alternate_be = BaseSite(
        category_urls={
            "https://www.alternate.be/CPUs": {"category": "cpu"},
            "https://www.alternate.be/Harde-schijven": {"category": "hdd"},
            "https://www.alternate.be/SSDs": {"category": "ssd"},
            "https://www.alternate.be/Grafische-kaarten": {"category": "gpu"},
            "https://www.alternate.be/Moederborden": {"category": "mobo"},
            "https://www.alternate.be/Voedingen": {"category": "psu"},
            "https://www.alternate.be/Geheugen": {"category": "ram"},
        },
        product_page_xpath="//a[contains(@class, 'productBox')]/@href",
        next_page_xpath="//a[@aria-label='Volgende pagina']/@href",
    )

    alternate_de = BaseSite(
        category_urls={
            "https://www.alternate.de/CPUs": {"category": "cpu"},
            "https://www.alternate.de/SSD": {"category": "ssd"},
            "https://www.alternate.de/Festplatten": {"category": "hdd"},
            "https://www.alternate.de/Grafikkarten": {"category": "gpu"},
            "https://www.alternate.de/Mainboards": {"category": "mobo"},
            "https://www.alternate.de/Netzteile": {"category": "psu"},
            "https://www.alternate.de/Arbeitsspeicher": {"category": "ram"},
        },
        product_page_xpath="//a[contains(@class, 'productBox')]/@href",
        next_page_xpath="//a[@aria-label='Nächste Seite']/@href",
    )

    arlt_com = BaseSite(
        category_urls={
            "https://www.arlt.com/Hardware/PC-Komponenten/Prozessoren/": {
                "category": "cpu"
            },
            "https://www.arlt.com/Hardware/PC-Komponenten/Solid-State-Drive-SSD/": {
                "category": "ssd"
            },
            "https://www.arlt.com/Hardware/PC-Komponenten/Festplatten/": {
                "category": "hdd"
            },
            "https://www.arlt.com/Hardware/PC-Komponenten/Grafikkarten/": {
                "category": "gpu"
            },
            "https://www.arlt.com/Hardware/PC-Komponenten/Mainboards/": {
                "category": "mobo"
            },
            "https://www.arlt.com/Hardware/PC-Komponenten/Netzteile/": {
                "category": "psu"
            },
            "https://www.arlt.com/Hardware/PC-Komponenten/Arbeitsspeicher/": {
                "category": "ram"
            },
        },
        product_page_xpath="//a[contains(@class, 'full-link')]/@href",
        next_page_xpath="//a[@aria-label='Weiter']/@href",
    )

    cybertek_fr = BaseSite(
        category_urls={
            "https://www.cybertek.fr/processeur-5.aspx": {"category": "cpu"},
            "https://www.cybertek.fr/disque-dur-interne-2-5-82.aspx": {
                "category": "hdd"
            },
            "https://www.cybertek.fr/disque-dur-interne-3-5-3.aspx": {
                "category": "hdd"
            },
            "https://www.cybertek.fr/disque-ssd-49.aspx": {"category": "ssd"},
            "https://www.cybertek.fr/carte-graphique-6.aspx": {"category": "gpu"},
            "https://www.cybertek.fr/carte-mere-4.aspx": {"category": "mobo"},
            "https://www.cybertek.fr/alimentation-12.aspx": {"category": "psu"},
            "https://www.cybertek.fr/memoire-pc-7.aspx": {"category": "ram"},
        },
        product_page_xpath="//a[contains(@class, 'grb__liste-produit__liste__produit__link')]/@href",
        next_page_xpath="//a[@rel='next' and contains(@class, 'fleche_mob')]/@href",
    )

    jacob_de = BaseSite(
        category_urls={
            "https://www.jacob.de/prozessoren-cpu/": {"category": "cpu"},
            "https://www.jacob.de/ddr5-ram-speichermodule/": {"category": "ram"},
            "https://www.jacob.de/ddr4-ram-speichermodule/": {"category": "ram"},
            "https://www.jacob.de/ddr3-ram-speichermodule/": {"category": "ram"},
            "https://www.jacob.de/ddr2-ram-speichermodule/": {"category": "ram"},
            "https://www.jacob.de/interne-hdd-festplatten": {"category": "hdd"},
            "https://www.jacob.de/interne-ssd-festplatten/": {"category": "ssd"},
            "https://www.jacob.de/grafikkarten/": {"category": "gpu"},
            "https://www.jacob.de/mainboards-motherboards/": {"category": "mobo"},
            "https://www.jacob.de/pc-netzteile/": {"category": "psu"},
        },
        product_page_xpath="//a[contains(@class, 'c1_product__title')]/@href",
        next_page_xpath="//a[contains(@class, 'next-item')]/@href",
    )

    amazon_de = BaseSite(
        category_urls={
            "http://www.amazon.de/s?k=grafikkarte+1070": {
                "category": "amazon_de_rtx_1070"
            },
        },
        product_page_xpath="//div[@data-component-type='s-search-result']//h2/ancestor::a",
        next_page_xpath="//a[contains(@class, 's-pagination-next')]",
        title_xpath="//span[@id='productTitle']//text()",
    )

 # Definition for ComputerUniverse using the selectors derived from your HTML
    computeruniverse_net = DynamicSite(
        category_urls={
            "https://www.computeruniverse.net/en/c/laptops-tablet-pcs-pcs/tablet-pcs": {"category": "gpu"}
        },
        # Targets the specific link inside the product headline
        product_page_xpath="//div[contains(@class, 'ProductListItemRow_head__name')]//a",
        
        # Targets the pagination button. 
        # We use [last()] to ensure we click 'Next' if a 'Previous' button is also present.
        next_page_xpath="(//button[@aria-label='Pagination naviButton'])[last()]",
        
        next_page_click=True,
        infinite_scroll=False,
        cookies_consent_xpath="//*[@id='consent-accept']"
    )
    # Initializes the Scraper
    # Passes all sites to the Scrapy implementation.
    # Runs a single reactor and crawls them concurrently based on Scrapy settings.
    # sites_to_crawl = [alternate_be, alternate_de, arlt_com, cybertek_fr, jacob_de]
    sites_to_crawl = [computeruniverse_net]

    # Instantiates the ScrapyScraper (other implementations like Selenium could be used here)

    crawlee_scraper = CrawleeScraper(sites=sites_to_crawl)
    # scrapy_scraper = ScrapyScraper()

    # Runs the generic crawl_all function
    # Iterates over the generator, which blocks until items start flowing in.
    logger.info("Starting generic crawl...")

    count = 0
    try:
        for product in crawl_all([crawlee_scraper]):
            count += 1
            # Access generic fields
            price_display = (
                f"{product.price} {product.currency}" if product.price else "N/A"
            )

            # Access custom metadata we injected above
            category = product.meta.get("category", "unknown")

            logger.info(
                f"[{count}] [{category}] {product.title[:50]}... | {price_display} | {product.url}"
            )

    except KeyboardInterrupt:
        logger.info("Crawl interrupted by user.")

    logger.info(f"Crawl finished. Total items: {count}")


if __name__ == "__main__":
    main()
