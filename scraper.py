"""
Book scraper for books.toscrape.com
Extracts all books across all category pages with title, price,
rating, stock status, and detail page URL.
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional
from urllib.parse import urljoin
from tqdm import tqdm

# --- Config ---
BASE_URL = "https://books.toscrape.com/"
START_URL = "https://books.toscrape.com/catalogue/page-1.html"
OUTPUT_DIR = Path("output")
REQUEST_DELAY = 0.5  # seconds between requests
MAX_PAGES = 50  # site has exactly 50 pages

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

RATING_MAP = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)


@dataclass
class Book:
    title: str
    price_gbp: float
    rating: int
    in_stock: bool
    url: str
    image_url: str
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

    def parse_book(self, card, page_url: str) -> Optional[Book]:
        """Extract book data from a single product_pod element."""
        try:
            title_el = card.select_one("h3 a")
            title = title_el["title"] if title_el else None

            relative_url = title_el["href"] if title_el else None
            url = urljoin(page_url, relative_url) if relative_url else None

            price_text = card.select_one("p.price_color").get_text(strip=True)
            # Strip currency symbol and any non-numeric chars
            price = float("".join(c for c in price_text if c.isdigit() or c == "."))

            rating_el = card.select_one("p.star-rating")
            rating_word = rating_el["class"][1] if rating_el else None
            rating = RATING_MAP.get(rating_word, 0)

            stock_el = card.select_one("p.instock.availability")
            in_stock = "in stock" in stock_el.get_text(strip=True).lower() if stock_el else False

            img_el = card.select_one("img.thumbnail")
            image_url = urljoin(page_url, img_el["src"]) if img_el else None

            return Book(
                title=title,
                price_gbp=price,
                rating=rating,
                in_stock=in_stock,
                url=url,
                image_url=image_url,
                scraped_at=pd.Timestamp.utcnow().isoformat(),
            )
        except Exception as e:
            log.warning(f"Failed to parse book card: {e}")
            return None

    def scrape_all(self, start_url: str, max_pages: int) -> list[Book]:
        """Scrape all pages, following the 'next' link."""
        books = []
        current_url = start_url

        for page_num in tqdm(range(1, max_pages + 1), desc="Pages"):
            soup = self.fetch(current_url)
            if not soup:
                break

            cards = soup.select("article.product_pod")
            for card in cards:
                book = self.parse_book(card, current_url)
                if book:
                    books.append(book)

            next_link = soup.select_one("li.next a")
            if not next_link:
                log.info(f"No more pages after page {page_num}")
                break
            current_url = urljoin(current_url, next_link["href"])

        return books


def save_output(books: list[Book]):
    OUTPUT_DIR.mkdir(exist_ok=True)
    df = pd.DataFrame([asdict(b) for b in books])

    csv_path = OUTPUT_DIR / "books.csv"
    json_path = OUTPUT_DIR / "books.json"

    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_json(json_path, orient="records", indent=2, force_ascii=False)

    log.info(f"Saved {len(books)} books to {csv_path} and {json_path}")
    log.info(f"\nStats:")
    log.info(f"  Total books:    {len(df)}")
    log.info(f"  Avg price:      £{df['price_gbp'].mean():.2f}")
    log.info(f"  Avg rating:     {df['rating'].mean():.2f} / 5")
    log.info(f"  In stock:       {df['in_stock'].sum()} / {len(df)}")


def main():
    scraper = Scraper()
    books = scraper.scrape_all(START_URL, max_pages=MAX_PAGES)
    if books:
        save_output(books)
    else:
        log.error("No books scraped. Something went wrong.")


if __name__ == "__main__":
    main()