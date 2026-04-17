# E-commerce Product Scraper

A production-ready Python scraper that extracts product data from e-commerce category pages, handling pagination, price parsing, stock status, and discount calculation.

## Features
- Extracts product title, current/original price, discount %, stock status, URL, and image
- Automatic pagination handling
- Retry logic with exponential backoff
- Polite rate limiting
- Outputs both CSV and JSON
- Structured logging

## Tech stack
Python 3.12, requests, BeautifulSoup4, pandas, tqdm

## Usage
\`\`\`bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python scraper.py
\`\`\`

## Responsible scraping
This scraper respects robots.txt, uses polite rate limiting, identifies itself with a standard User-Agent, and scrapes only publicly accessible data.