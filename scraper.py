"""
E-commerce product scraper for The Works (theworks.co.uk)
Extracts product data from category pages with pagination support.
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import time
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urljoin
from tqdm import tqdm

# --- Config ---
BASE_URL = "https://www.theworks.co.uk"
CATEGORY_URL = "https://www.theworks.co.uk/c/books"
OUTPUT_DIR = Path("output")
REQUEST_DELAY = 1.5  # seconds between requests — be polite
MAX_PAGES = 5  # cap for portfolio demo; remove for full scrape

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)


@dataclass
class Product:
    title: str
    price: Optional[float]
    original_price: Optional[float]
    discount_pct: Optional[float]
    in_stock: bool
    url: str
    image_url: Optional[str]
    scraped_at: str


class Scraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch a URL with retries and polite delay."""
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
                time.sleep(REQUEST_DELAY)
                return BeautifulSoup(resp.text, "lxml")
            except requests.RequestException as e:
                log.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                time.sleep(2 ** attempt)
        log.error(f"Giving up on {url}")
        return None

    def parse_product_card(self, card) -> Optional[Product]:
        """Extract product data from a single product card element.
        
        NOTE: selectors will need adjusting based on the site's actual HTML.
        Run this once, inspect the output, and tweak.
        """
        try:
            title_el = card.select_one("[data-testid='product-title'], .product-title, h3 a")
            title = title_el.get_text(strip=True) if title_el else None

            link_el = card.select_one("a[href*='/p/']")
            url = urljoin(BASE_URL, link_el["href"]) if link_el else None

            price_el = card.select_one(".price-now, .product-price, [data-testid='price']")
            price = self._parse_price(price_el.get_text() if price_el else None)

            original_el = card.select_one(".price-was, .original-price, del")
            original = self._parse_price(original_el.get_text() if original_el else None)

            discount = None
            if price and original and original > price:
                discount = round((original - price) / original * 100, 1)

            img_el = card.select_one("img")
            image_url = img_el.get("src") or img_el.get("data-src") if img_el else None

            stock_el = card.select_one(".out-of-stock, .stock-status")
            in_stock = not (stock_el and "out" in stock_el.get_text(strip=True).lower())

            if not title or not url:
                return None

            return Product(
                title=title,
                price=price,
                original_price=original,
                discount_pct=discount,
                in_stock=in_stock,
                url=url,
                image_url=image_url,
                scraped_at=pd.Timestamp.utcnow().isoformat(),
            )
        except Exception as e:
            log.warning(f"Failed to parse card: {e}")
            return None

    @staticmethod
    def _parse_price(text: Optional[str]) -> Optional[float]:
        if not text:
            return None
        cleaned = "".join(c for c in text if c.isdigit() or c == ".")
        try:
            return float(cleaned) if cleaned else None
        except ValueError:
            return None

    def scrape_category(self, start_url: str, max_pages: int = 5) -> list[Product]:
        """Scrape a category with pagination."""
        products = []
        current_url = start_url

        for page_num in tqdm(range(1, max_pages + 1), desc="Pages"):
            log.info(f"Scraping page {page_num}: {current_url}")
            soup = self.fetch(current_url)
            if not soup:
                break

            cards = soup.select("[data-testid='product-card'], .product-card, .product-item")
            log.info(f"Found {len(cards)} product cards on page {page_num}")

            for card in cards:
                product = self.parse_product_card(card)
                if product:
                    products.append(product)

            next_link = soup.select_one("a[rel='next'], .pagination-next a")
            if not next_link or not next_link.get("href"):
                log.info("No more pages")
                break
            current_url = urljoin(BASE_URL, next_link["href"])

        return products


def save_output(products: list[Product]):
    OUTPUT_DIR.mkdir(exist_ok=True)
    df = pd.DataFrame([asdict(p) for p in products])

    csv_path = OUTPUT_DIR / "products.csv"
    json_path = OUTPUT_DIR / "products.json"

    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_json(json_path, orient="records", indent=2, force_ascii=False)

    log.info(f"Saved {len(products)} products to {csv_path} and {json_path}")
    log.info(f"\nSummary:\n{df.describe(include='all')}")


def main():
    scraper = Scraper()
    products = scraper.scrape_category(CATEGORY_URL, max_pages=MAX_PAGES)
    if products:
        save_output(products)
    else:
        log.error("No products scraped. Check your selectors.")


if __name__ == "__main__":
    main()