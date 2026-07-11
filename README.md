# Live E-Commerce Price Tracker Web

A clean, single-library web application built in Python that dynamically scrapes e-commerce product pages to track pricing data and deliver live budgetary notifications directly on a visual dashboard.

**Live Link:** _run locally — see Getting Started below_

## ✨ Features

- **Zero-API Web Scraping**: Extracts raw product metadata and localized price values seamlessly using structural HTML parsing (JSON-LD, meta tags, and price-pattern fallback).
- **Dynamic UI State Management**: Employs real-time visual metric variations and notification alerts without full-page reloads, powered by Streamlit's session state and rerun model.
- **Custom Budget Interactivity**: Empowers users to input distinct item targets and adjust threshold configurations on the fly, with instant "under budget" alerts.
- **Currency & country selection**: Tag each tracked item with the country/region and currency it's listed in, then view your whole dashboard converted into a single display currency using live exchange rates.
- **Price stats & rough sale timing**: See average, lowest, and highest price seen for each item, plus a rough estimate of when the next price drop might land, based on that item's own drop history.

## 🛠️ Built With

- **Python** (core application logic)
- **Streamlit** (single-library GUI/dashboard framework)
- **BeautifulSoup4** (HTML parsing and structural web data extraction)
- **Requests** (HTTP network communication protocol, also used for live exchange rates)

## Getting Started

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL Streamlit prints (usually `http://localhost:8501`).

## How it works

1. Paste a product page URL in the sidebar, pick the item's country/region and the currency the site lists it in, and set an optional budget target, then click **Start tracking**.
2. `app.py` fetches the page with `requests` and parses it with `BeautifulSoup4`, trying — in order — JSON-LD structured data, common price/meta tags, then a regex fallback over visible text.
3. Tracked products and their full price history (with timestamps) are stored in `tracked_products.json` so they persist across restarts.
4. Pick a **display currency** in the sidebar — every price on the dashboard converts to it live, using hourly-cached rates from a free exchange-rate API.
5. Click **Refresh all prices now**, or enable **Auto-refresh**, to re-scrape and update the dashboard in place — no page navigation, just Streamlit's rerun.
6. Each card shows the item's average / lowest / highest price seen so far, and — once there's enough history — a rough estimate of when the next price drop might happen, based on how often past drops occurred for that item.

## About the sale-timing estimate

This is **not a prediction from retailer data** — there's no public feed of upcoming sales. It's a simple pattern derived from the price history *you've* collected: once an item has had at least two recorded drops, the app averages the gap between them and estimates roughly when the next one might land. With little or no history, it says so honestly rather than guessing. The more days you track an item, the more useful this gets.

## Design

The dashboard uses a custom theme layered on top of Streamlit via CSS injection (see the `<style>` block near the top of the UI section in `app.py`):

- Warm parchment background with a deep teal accent for "under budget" states and rust/amber for price increases
- Space Mono for prices, labels, and headings; Inter for body text
- Custom-styled metric cards, product cards, and buttons instead of Streamlit's defaults

Streamlit's internal CSS class names can shift between versions, so the theme targets `data-testid` attributes (e.g. `stMetric`, `stVerticalBlockBorderWrapper`) rather than generated class names — these are the most stable hooks Streamlit exposes. If an upgrade ever breaks the look, that's the first place to check.

## Notes & limitations

- Scraping accuracy depends on each site's public HTML — pages that require JavaScript rendering or block automated requests may not return a price. This is a general-purpose extractor, not tuned to a specific retailer.
- The country/currency fields are metadata you set when adding an item — the app doesn't search a country's version of a site for you. You still paste in the correct region-specific product URL yourself (e.g. amazon.co.uk vs amazon.com).
- Currency conversion depends on a free third-party exchange-rate API; if it's unreachable, prices fall back to each item's original listing currency.
- Respect each site's `robots.txt` and terms of service when scraping.
- This is a starter/reference implementation — for production use you'd want retry/backoff logic, per-domain selector overrides, and rate limiting.

