"""
Book scraper for books.toscrape.com

Two-stage pipeline:
    1. Scrape all 50 listing pages to collect book URLs and list-level fields.
    2. Concurrently fetch each book's detail page for richer data (description,
    category, UPC, etc).
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import logging
import re
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional
from urllib.parse import urljoin
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Config ---
BASE_URL = "https://books.toscrape.com/"
START_URL = "https://books.toscrape.com/catalogue/page-1.html"
OUTPUT_DIR = Path("output")
REQUEST_DELAY = 0.1 # per-worker delay between requests
MAX_PAGES = 50  # site has exactly 50 pages
MAX_WORKERS = 10  # concurrent detail-page workers

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
    # List-level fields (from the category pages)
    title: str
    price_gbp: float
    rating: int
    in_stock: bool
    url: str
    image_url: str

    # Detail-level fields (from the individual book pages)
    description: Optional[str] = None
    upc: Optional[str] = None
    product_type: Optional[str] = None
    price_excl_tax: Optional[float] = None
    price_incl_tax: Optional[float] = None
    tax: Optional[float] = None
    availability_count: Optional[int] = None
    num_reviews: Optional[int] = None
    category: Optional[str] = None

    scraped_at: str = field(default_factory=lambda: pd.Timestamp.utcnow().isoformat())
    


class Scraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def fetch(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch a URL with retries and polite delay. Thread-safe."""
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

    # Listing pages.

    def parse_listing_page(self, page, page_url: str) -> Optional[Book]:
        """Extract list-level book data from a product_pod element."""
        try:
            title_el = page.select_one("h3 a")
            title = title_el["title"]
            url = urljoin(page_url, title_el["href"])

            price_text = page.select_one("p.price_color").get_text(strip=True)
            price = float("".join(c for c in price_text if c.isdigit() or c == "."))

            rating_word = page.select_one("p.star-rating")["class"][1]
            rating = RATING_MAP.get(rating_word, 0)

            stock_text = page.select_one("p.instock.availability").get_text(strip=True).lower()
            in_stock = "in stock" in stock_text

            img_el = page.select_one("img.thumbnail")
            image_url = urljoin(page_url, img_el["src"])

            return Book(
                title=title,
                price_gbp=price,
                rating=rating,
                in_stock=in_stock,
                url=url,
                image_url=image_url,
            )
        except Exception as e:
            log.warning(f"Failed to parse listing page book: {e}")
            return None

    def scrape_listings(self, start_url: str, max_pages: int) -> list[Book]:
        """Stage 1: walk all listing pages and build book objects."""
        books = []
        current_url = start_url

        for page_num in tqdm(range(1, max_pages + 1), desc="Pages"):
            soup = self.fetch(current_url)
            if not soup:
                break

            cards = soup.select("article.product_pod")
            for card in cards:
                book = self.parse_listing_page(card, current_url)
                if book:
                    books.append(book)

            next_link = soup.select_one("li.next a")
            if not next_link:
                log.info(f"No more pages after page {page_num}")
                break
            current_url = urljoin(current_url, next_link["href"])

        return books
        
        # Detail pages

    def enrich_with_detail(self, book: Book) -> Book:
        """Fetch the detail page and populate the detail-level fields on the Book."""
        soup = self.fetch(book.url)
        if not soup:
            return book  # return with detail fields as None

        try:
            # Description: the first <p> after the #product_description heading
            desc_header = soup.select_one("#product_description")
            if desc_header:
                desc_p = desc_header.find_next_sibling("p")
                book.description = desc_p.get_text(strip=True) if desc_p else None

            # Category: third breadcrumb item (Home > Books > {Category} > {Title})
            breadcrumbs = soup.select("ul.breadcrumb li")
            if len(breadcrumbs) >= 3:
                book.category = breadcrumbs[2].get_text(strip=True)

            # The product info table — each <th>/<td> pair is one attribute
            info_rows = soup.select("table.table-striped tr")
            info = {row.th.get_text(strip=True): row.td.get_text(strip=True)
                    for row in info_rows}

            book.upc = info.get("UPC")
            book.product_type = info.get("Product Type")
            book.price_excl_tax = self._money(info.get("Price (excl. tax)"))
            book.price_incl_tax = self._money(info.get("Price (incl. tax)"))
            book.tax = self._money(info.get("Tax"))

            # Availability: e.g. "In stock (22 available)" → 22
            avail_text = info.get("Availability", "")
            match = re.search(r"(\d+)", avail_text)
            book.availability_count = int(match.group(1)) if match else None

            # Reviews: just a plain integer in the table
            reviews_text = info.get("Number of reviews", "0")
            book.num_reviews = int(reviews_text) if reviews_text.isdigit() else 0

        except Exception as e:
            log.warning(f"Failed to parse detail page {book.url}: {e}")

        return book

    @staticmethod
    def _money(text: Optional[str]) -> Optional[float]:
        """Parse a price string like '£51.77' or 'Â£51.77' into a float."""
        if not text:
            return None
        cleaned = "".join(c for c in text if c.isdigit() or c == ".")
        return float(cleaned) if cleaned else None

    def scrape_details(self, books: list[Book], max_workers: int) -> list[Book]:
        """Stage 2: concurrently fetch detail pages for every book."""
        enriched = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.enrich_with_detail, b): b for b in books}
            for future in tqdm(as_completed(futures), total=len(futures), desc="Details"):
                try:
                    enriched.append(future.result())
                except Exception as e:
                    # Should not happen thanks to the inner try/except, but just in case
                    original = futures[future]
                    log.error(f"Unhandled error enriching {original.url}: {e}")
                    enriched.append(original)
        return enriched
    

def save_output(books: list[Book]):
    OUTPUT_DIR.mkdir(exist_ok=True)
    df = pd.DataFrame([asdict(b) for b in books])

    csv_path = OUTPUT_DIR / "books.csv"
    json_path = OUTPUT_DIR / "books.json"

    df.to_csv(csv_path, index=False, encoding="utf-8")
    df.to_json(json_path, orient="records", indent=2, force_ascii=False)

    log.info(f"Saved {len(books)} books to {csv_path} and {json_path}")
    log.info("")
    log.info("Summary:")
    log.info(f"  Total books:         {len(df)}")
    log.info(f"  Avg price (GBP):     £{df['price_gbp'].mean():.2f}")
    log.info(f"  Avg rating:          {df['rating'].mean():.2f} / 5")
    log.info(f"  Avg stock on hand:   {df['availability_count'].mean():.1f}")
    log.info(f"  Distinct categories: {df['category'].nunique()}")
    log.info(f"  Books with reviews:  {(df['num_reviews'] > 0).sum()}")


def main():
    start = time.time()
    scraper = Scraper()

    log.info("Stage 1: scraping listing pages...")
    books = scraper.scrape_listings(START_URL, max_pages=MAX_PAGES)
    log.info(f"Collected {len(books)} books from listings")

    log.info(f"Stage 2: fetching detail pages with {MAX_WORKERS} workers...")
    books = scraper.scrape_details(books, max_workers=MAX_WORKERS)

    if books:
        save_output(books)
        log.info(f"\nTotal runtime: {time.time() - start:.1f}s")
    else:
        log.error("No books scraped.")


if __name__ == "__main__":
    main()