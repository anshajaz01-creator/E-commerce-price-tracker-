"""
Live E-Commerce Price Tracker
A single-library (Streamlit) GUI that scrapes product pages with
requests + BeautifulSoup4, tracks price history, converts currency
live, and gives rough sale-timing estimates based on that history.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

DATA_FILE = Path(__file__).parent / "tracked_products.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
PRICE_PATTERN = re.compile(r"[\$£€]\s?\d{1,3}(?:[,.\s]\d{3})*(?:\.\d{2})?")

CURRENCIES = ["USD", "EUR", "GBP", "PKR", "INR", "AED", "CAD", "AUD", "JPY", "CNY"]
COUNTRIES = [
    "United States", "United Kingdom", "Pakistan", "India", "UAE",
    "Canada", "Australia", "Japan", "China", "Germany", "Other",
]


# ---------------------------------------------------------------------
# Scraping layer (requests + BeautifulSoup4, no external API)
# ---------------------------------------------------------------------

def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    return resp.text


def extract_title(soup: BeautifulSoup) -> str:
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return og_title["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return "Unnamed product"


def _price_from_jsonld(soup: BeautifulSoup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            offers = item.get("offers") if isinstance(item, dict) else None
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict) and offers.get("price"):
                try:
                    return float(str(offers["price"]).replace(",", ""))
                except ValueError:
                    continue
    return None


def _price_from_meta(soup: BeautifulSoup):
    for attrs in (
        {"property": "og:price:amount"},
        {"property": "product:price:amount"},
        {"itemprop": "price"},
    ):
        tag = soup.find("meta", attrs=attrs) or soup.find(attrs=attrs)
        if tag:
            value = tag.get("content") or tag.get_text(strip=True)
            if value:
                try:
                    return float(re.sub(r"[^\d.]", "", value))
                except ValueError:
                    continue
    return None


def _price_from_text(soup: BeautifulSoup):
    price_like = soup.find_all(class_=re.compile("price", re.I))
    for tag in price_like:
        match = PRICE_PATTERN.search(tag.get_text(" ", strip=True))
        if match:
            return float(re.sub(r"[^\d.]", "", match.group()))
    match = PRICE_PATTERN.search(soup.get_text(" ", strip=True))
    if match:
        return float(re.sub(r"[^\d.]", "", match.group()))
    return None


def extract_price(soup: BeautifulSoup):
    for extractor in (_price_from_jsonld, _price_from_meta, _price_from_text):
        price = extractor(soup)
        if price is not None:
            return round(price, 2)
    return None


def scrape_product(url: str) -> dict:
    html = fetch_html(url)
    soup = BeautifulSoup(html, "html.parser")
    price = extract_price(soup)
    if price is None:
        raise ValueError("Could not find a price on that page.")
    return {
        "name": extract_title(soup),
        "price": price,
        "retailer": urlparse(url).netloc.replace("www.", ""),
    }


# ---------------------------------------------------------------------
# Currency conversion (free, keyless exchange-rate API)
# ---------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_exchange_rates(base: str = "USD"):
    """Rates are per 1 unit of `base`. Cached for an hour to limit calls."""
    resp = requests.get(f"https://api.exchangerate-api.com/v4/latest/{base}", timeout=8)
    resp.raise_for_status()
    return resp.json()["rates"]


def convert_price(amount: float, from_cur: str, to_cur: str, rates: dict) -> float:
    if amount is None or from_cur == to_cur or not rates:
        return amount
    if from_cur not in rates or to_cur not in rates:
        return amount
    amount_in_base = amount / rates[from_cur]
    return amount_in_base * rates[to_cur]


# ---------------------------------------------------------------------
# History analysis: averages + rough sale-timing estimate
# ---------------------------------------------------------------------

def analyze_history(history: list) -> dict:
    prices = [h["price"] for h in history]
    result = {
        "avg": sum(prices) / len(prices),
        "low": min(prices),
        "high": max(prices),
        "legacy": False,
        "days_tracked": None,
        "days_since_drop": None,
        "avg_interval_days": None,
        "next_estimate_days": None,
    }
    try:
        parsed = [(datetime.fromisoformat(h["t"]), h["price"]) for h in history]
    except ValueError:
        # Data saved before this feature was added has no date info.
        result["legacy"] = True
        return result

    result["days_tracked"] = (parsed[-1][0] - parsed[0][0]).days

    drop_dates = [parsed[i][0] for i in range(1, len(parsed)) if parsed[i][1] < parsed[i - 1][1]]
    if drop_dates:
        result["days_since_drop"] = (datetime.now() - drop_dates[-1]).days
    if len(drop_dates) >= 2:
        intervals = [(drop_dates[i] - drop_dates[i - 1]).days for i in range(1, len(drop_dates))]
        avg_interval = sum(intervals) / len(intervals)
        result["avg_interval_days"] = avg_interval
        if result["days_since_drop"] is not None:
            result["next_estimate_days"] = max(round(avg_interval - result["days_since_drop"]), 0)
    return result


def sale_estimate_text(stats: dict) -> str:
    if stats["legacy"]:
        return "Upgrade needed: this item's history predates sale-timing tracking. Remove and re-add it to enable this."
    if stats["days_since_drop"] is None:
        return "No price drop recorded yet — check back after tracking longer."
    if stats["avg_interval_days"] is None:
        return f"Last dropped {stats['days_since_drop']} day(s) ago. Need one more drop to estimate a pattern."
    if stats["next_estimate_days"] == 0:
        return f"Historically dips every ~{stats['avg_interval_days']:.0f} days — a drop may be due any day now."
    return (
        f"Historically dips every ~{stats['avg_interval_days']:.0f} days — "
        f"next drop estimated in ~{stats['next_estimate_days']} day(s). Rough estimate, not a guarantee."
    )


# ---------------------------------------------------------------------
# Persistence (simple JSON file so tracked items survive restarts)
# ---------------------------------------------------------------------

def load_products() -> list:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text())
    return []


def save_products(products: list) -> None:
    DATA_FILE.write_text(json.dumps(products, indent=2))


# ---------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------

if "products" not in st.session_state:
    st.session_state.products = load_products()
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()


def add_product(url: str, target: float, country: str, currency: str):
    info = scrape_product(url)
    entry = {
        "id": str(int(time.time() * 1000)),
        "url": url,
        "name": info["name"],
        "retailer": info["retailer"],
        "target": target,
        "country": country,
        "currency": currency,
        "history": [{"t": datetime.now().isoformat(), "price": info["price"]}],
    }
    st.session_state.products.append(entry)
    save_products(st.session_state.products)


def refresh_product(entry: dict):
    info = scrape_product(entry["url"])
    entry["history"].append({"t": datetime.now().isoformat(), "price": info["price"]})
    entry["history"] = entry["history"][-60:]


def refresh_all():
    for entry in st.session_state.products:
        try:
            refresh_product(entry)
        except Exception as exc:
            st.warning(f"Couldn't refresh {entry['name']}: {exc}")
    save_products(st.session_state.products)
    st.session_state.last_refresh = time.time()


def remove_product(product_id: str):
    st.session_state.products = [p for p in st.session_state.products if p["id"] != product_id]
    save_products(st.session_state.products)


# ---------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------

st.set_page_config(page_title="Price Watch", page_icon="🏷️", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Inter:wght@400;500;600&display=swap');

    :root {
        --pw-bg: #F6F1E4;
        --pw-surface: #FFFFFF;
        --pw-ink: #241C15;
        --pw-muted: #8A7F6A;
        --pw-accent: #1F6F5C;
        --pw-accent-soft: rgba(31,111,92,0.12);
        --pw-rise: #B5651D;
        --pw-rise-soft: rgba(181,101,29,0.12);
        --pw-border: rgba(36,28,21,0.12);
    }

    html, body, [data-testid="stAppViewContainer"] {
        background: var(--pw-bg);
        color: var(--pw-ink);
        font-family: 'Inter', sans-serif;
    }
    [data-testid="stHeader"] { background: transparent; }

    [data-testid="stSidebar"] {
        background: var(--pw-surface);
        border-right: 1px solid var(--pw-border);
    }
    [data-testid="stSidebar"] h2 {
        font-family: 'Space Mono', monospace;
        font-size: 14px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--pw-ink);
    }

    .pw-hero {
        padding: 8px 0 4px;
        border-bottom: 1px solid var(--pw-border);
        margin-bottom: 22px;
    }
    .pw-eyebrow {
        font-family: 'Space Mono', monospace;
        font-size: 12px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--pw-accent);
        margin: 0 0 6px;
    }
    .pw-title {
        font-family: 'Space Mono', monospace;
        font-weight: 700;
        font-size: 30px;
        margin: 0 0 6px;
        color: var(--pw-ink);
    }
    .pw-subtitle {
        font-size: 14px;
        color: var(--pw-muted);
        margin: 0 0 18px;
    }

    [data-testid="stMetric"] {
        background: var(--pw-surface);
        border: 1px solid var(--pw-border);
        border-radius: 10px;
        padding: 14px 16px;
    }
    [data-testid="stMetricLabel"] {
        font-family: 'Space Mono', monospace;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--pw-muted);
    }
    [data-testid="stMetricValue"] {
        font-family: 'Space Mono', monospace;
        color: var(--pw-ink);
    }

    [data-testid="stVerticalBlockBorderWrapper"] {
        background: var(--pw-surface);
        border: 1px solid var(--pw-border) !important;
        border-radius: 12px !important;
        box-shadow: 0 1px 2px rgba(36,28,21,0.04);
        padding: 4px 4px 8px;
    }

    .below-budget {
        display: inline-block;
        color: var(--pw-accent);
        background: var(--pw-accent-soft);
        font-size: 12px;
        font-weight: 600;
        padding: 3px 9px;
        border-radius: 20px;
        margin-top: 4px;
    }

    .pw-tag {
        display: inline-block;
        font-size: 11px;
        color: var(--pw-muted);
        background: rgba(36,28,21,0.06);
        padding: 2px 8px;
        border-radius: 20px;
        margin: 0 6px 4px 0;
    }

    .pw-sale-note {
        font-size: 12px;
        color: var(--pw-muted);
        line-height: 1.4;
        margin: 6px 0 0;
    }

    .pw-stats-line {
        font-family: 'Space Mono', monospace;
        font-size: 12px;
        color: var(--pw-muted);
        margin: 4px 0 0;
    }

    .stButton > button, .stFormSubmitButton > button {
        border-radius: 8px;
        border: 1px solid var(--pw-border);
        font-family: 'Inter', sans-serif;
        font-weight: 500;
    }
    .stFormSubmitButton > button {
        background: var(--pw-ink);
        color: var(--pw-bg);
        border: none;
    }

    hr, [data-testid="stDivider"] { border-color: var(--pw-border) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Track a product")
    with st.form("add_product_form", clear_on_submit=True):
        url = st.text_input("Product page URL", placeholder="https://example.com/product/123")
        col_a, col_b = st.columns(2)
        country = col_a.selectbox("Country / region", COUNTRIES)
        currency = col_b.selectbox("Listing currency", CURRENCIES, help="The currency the site shows prices in.")
        target = st.number_input("Budget / target price", min_value=0.0, step=1.0, value=0.0)
        submitted = st.form_submit_button("Start tracking")
    if submitted and url:
        try:
            with st.spinner("Fetching product page..."):
                add_product(url, target, country, currency)
            st.success("Product added.")
        except Exception as exc:
            st.error(f"Scrape failed: {exc}")

    st.divider()
    st.header("Display")
    display_currency = st.selectbox("Show prices in", CURRENCIES, index=0)
    country_filter = st.selectbox("Filter by country", ["All"] + COUNTRIES)

    st.divider()
    st.header("Refresh")
    if st.button("🔄 Refresh all prices now"):
        with st.spinner("Checking prices..."):
            refresh_all()

    auto = st.checkbox("Auto-refresh", value=False)
    interval = st.slider("Interval (seconds)", 15, 300, 60, disabled=not auto)

    st.divider()
    st.caption(
        "Scraping relies on the target page's public HTML/meta tags. "
        "Some sites block automated requests or need site-specific selectors. "
        "Currency conversion uses live exchange rates, refreshed hourly."
    )

st.markdown(
    """
    <div class="pw-hero">
        <p class="pw-eyebrow">Price Watch</p>
        <p class="pw-title">Your watchlist</p>
        <p class="pw-subtitle">Live product price tracking with budget alerts, currency conversion, and rough sale-timing estimates.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

try:
    rates = fetch_exchange_rates("USD")
except Exception:
    rates = None
    st.warning("Couldn't reach the exchange-rate service — showing prices in each item's original currency.")

all_products = st.session_state.products
products = (
    all_products if country_filter == "All"
    else [p for p in all_products if p.get("country") == country_filter]
)

under_budget = []
total_savings_display = 0.0
for p in products:
    p_currency = p.get("currency", "USD")
    current = p["history"][-1]["price"]
    first = p["history"][0]["price"]
    current_display = convert_price(current, p_currency, display_currency, rates) if rates else current
    first_display = convert_price(first, p_currency, display_currency, rates) if rates else first
    target_display = (
        convert_price(p["target"], p_currency, display_currency, rates) if rates and p["target"] else p["target"]
    )
    if p["target"] and current_display <= target_display:
        under_budget.append(p)
    total_savings_display += max(first_display - current_display, 0)

col1, col2, col3 = st.columns(3)
col1.metric("Tracked products", len(products))
col2.metric("Under budget", len(under_budget))
col3.metric("Total potential savings", f"{total_savings_display:.2f} {display_currency}")

st.divider()

if not products:
    st.info("No products tracked yet. Add one from the sidebar to get started.")
else:
    for alert in under_budget:
        st.toast(f"🎉 {alert['name']} is under your {display_currency} target!")

    cols = st.columns(3)
    for i, product in enumerate(products):
        history = product["history"]
        p_currency = product.get("currency", "USD")
        stats = analyze_history(history)

        current = convert_price(history[-1]["price"], p_currency, display_currency, rates) if rates else history[-1]["price"]
        previous_raw = history[-2]["price"] if len(history) > 1 else history[-1]["price"]
        previous = convert_price(previous_raw, p_currency, display_currency, rates) if rates else previous_raw
        delta = current - previous

        avg_disp = convert_price(stats["avg"], p_currency, display_currency, rates) if rates else stats["avg"]
        low_disp = convert_price(stats["low"], p_currency, display_currency, rates) if rates else stats["low"]
        high_disp = convert_price(stats["high"], p_currency, display_currency, rates) if rates else stats["high"]
        target_disp = (
            convert_price(product["target"], p_currency, display_currency, rates)
            if rates and product["target"] else product["target"]
        )

        with cols[i % 3]:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div style="padding:12px 14px 0;">
                        <span class="pw-tag">{product['retailer']}</span>
                        <span class="pw-tag">{product.get('country', 'Other')}</span>
                        <p style="font-size:14.5px;font-weight:600;margin:6px 0 8px;line-height:1.35;">
                            {product['name']}
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.metric(
                    f"Current price ({display_currency})",
                    f"{current:.2f}",
                    delta=f"{delta:+.2f}",
                    delta_color="inverse",
                )
                st.markdown(
                    f'<p class="pw-stats-line">Avg {avg_disp:.2f} · Low {low_disp:.2f} · High {high_disp:.2f}</p>',
                    unsafe_allow_html=True,
                )
                if product["target"]:
                    if current <= target_disp:
                        st.markdown(
                            f'<span class="below-budget">✅ Under target ({target_disp:.2f} {display_currency})</span>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.caption(f"Target: {target_disp:.2f} {display_currency}")
                st.markdown(f'<p class="pw-sale-note">{sale_estimate_text(stats)}</p>', unsafe_allow_html=True)
                if len(history) > 1:
                    st.line_chart({"price": [h["price"] for h in history]}, height=120)
                if st.button("Stop tracking", key=f"remove_{product['id']}"):
                    remove_product(product["id"])
                    st.rerun()

# Lightweight auto-refresh loop: reruns the script in place (same session,
# no browser navigation) once the interval elapses.
if auto and time.time() - st.session_state.last_refresh >= interval:
    refresh_all()
    st.rerun()
