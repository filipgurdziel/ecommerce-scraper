# E-commerce Product Scraper

A production-ready two-stage concurrent scrapter that extracts 16 fields per book across 1000 products.

Demonstrated on [books.toscrape.com](https://books.toscrape.com) — successfully scraped all 1000 books across 50 pages in under a minute.

## Features
- Extracts title, price, rating (1-5 stars), stock status, product URL, and image URL
- After extracting basic details (from listing page), extracts richer information from individual book pages
- Extracting from individual book pages concurrently
- Automatic pagination - follows the site's "next" link until the last page
- Retry logic with exponential backoff (handles transient network failures)
- Polite rate limiting (configurable delay between requests)
- Structured logging with timestamps and severity levels
- Outputs both CSV and JSON for downstream use
- Graceful degradation - one malformed product doesn't kill the scrape

## Pipeline
- Stage 1 (listings); visit category pages, scrape the basics (title, price, star ratings, stock yes/no, cover image, and the URL)
- Stage 2 (detailed); visit each individual book page, scrape more information (full description, UPC code, tax breakdown, exact stock count, number of reviews, category), then merge back into book object.


## Sample output

![Sample CSV output](sample_output.png)

Summary stats from a full run:
- **Total books scraped:** 1000
- **Pages processed:** 50
- **Avg price:** £35.07
- **Avg rating:** 2.92 / 5
- **Runtime:** ~35 seconds

## Tech stack
- Python 3.12
- `requests` - HTTP client with session reuse
- `BeautifulSoup4` + `lxml` - fast HTML parsing
- `pandas` - data output to CSV/JSON
- `tqdm` - progress indicator
- `dataclasses` + type hints for clean, maintainable code
- `concurrent.features` - concurrency, allows extracting multiple items at the same time

## Usage

```bash
git clone git@github.com:filipgurdziel/ecommerce-scraper.git
cd ecommerce-scraper
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python scraper.py
```

Output lands in `output/books.csv` and `output/books.json`.

## Configuration

Edit the constants at the top of `scraper.py`:
- `START_URL`; where to begin scraping
- `MAX_PAGES`; upper limit on pages to process
- `REQUEST_DELAY`; seconds between requests (default: 0.5)

## Adapting to other sites

The scraper is structured around three extension points:
1. **`Scraper.fetch()`**; HTTP layer (rarely needs changes)
2. **`Scraper.parse_book()`**; update CSS selectors for your target site
3. **`Book` dataclass**; add or remove fields as needed

For JavaScript-heavy sites (React SPAs, lazy-loaded content), swap `requests + BeautifulSoup` for `Playwright`.

## Responsible scraping

This scraper:
- Respects `robots.txt`
- Uses polite rate limiting
- Identifies itself with a standard User-Agent
- Scrapes only publicly accessible data

If adapting for production use, ensure compliance with the target site's Terms of Service and applicable data protection laws (GDPR, etc.).

## License

MIT — see [LICENSE](LICENSE)
