"""
Live E-Commerce Price Tracker
A single-library (Streamlit) GUI that scrapes product pages with
requests + BeautifulSoup4 and displays live price/budget tracking.
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


def add_product(url: str, target: float):
    info = scrape_product(url)
    entry = {
        "id": str(int(time.time() * 1000)),
        "url": url,
        "name": info["name"],
        "retailer": info["retailer"],
        "target": target,
        "history": [{"t": datetime.now().strftime("%H:%M:%S"), "price": info["price"]}],
    }
    st.session_state.products.append(entry)
    save_products(st.session_state.products)


def refresh_product(entry: dict):
    info = scrape_product(entry["url"])
    entry["history"].append({"t": datetime.now().strftime("%H:%M:%S"), "price": info["price"]})
    entry["history"] = entry["history"][-30:]


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
        target = st.number_input("Budget / target price ($)", min_value=0.0, step=1.0, value=0.0)
        submitted = st.form_submit_button("Start tracking")
    if submitted and url:
        try:
            with st.spinner("Fetching product page..."):
                add_product(url, target)
            st.success("Product added.")
        except Exception as exc:
            st.error(f"Scrape failed: {exc}")

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
        "Some sites block automated requests or need site-specific selectors."
    )

st.markdown(
    """
    <div class="pw-hero">
        <p class="pw-eyebrow">Price Watch</p>
        <p class="pw-title">Your watchlist</p>
        <p class="pw-subtitle">Live product price tracking with budget alerts — scraped directly from product pages.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

products = st.session_state.products
col1, col2, col3 = st.columns(3)
under_budget = [
    p for p in products
    if p["target"] and p["history"][-1]["price"] <= p["target"]
]
col1.metric("Tracked products", len(products))
col2.metric("Under budget", len(under_budget))
col3.metric(
    "Total potential savings",
    f"${sum(max(p['history'][0]['price'] - p['history'][-1]['price'], 0) for p in products):.2f}"
    if products else "$0.00",
)

st.divider()

if not products:
    st.info("No products tracked yet. Add one from the sidebar to get started.")
else:
    for alert in under_budget:
        st.toast(f"🎉 {alert['name']} is at ${alert['history'][-1]['price']:.2f} — under your ${alert['target']:.2f} target!")

    cols = st.columns(3)
    for i, product in enumerate(products):
        history = product["history"]
        current = history[-1]["price"]
        previous = history[-2]["price"] if len(history) > 1 else current
        delta = current - previous

        with cols[i % 3]:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div style="padding:12px 14px 0;">
                        <p style="font-family:'Space Mono',monospace;font-size:11px;
                            text-transform:uppercase;letter-spacing:0.06em;color:var(--pw-muted);margin:0 0 4px;">
                            {product['retailer']}
                        </p>
                        <p style="font-size:14.5px;font-weight:600;margin:0 0 8px;line-height:1.35;">
                            {product['name']}
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.metric("Current price", f"${current:.2f}", delta=f"{delta:+.2f}", delta_color="inverse")
                if product["target"]:
                    if current <= product["target"]:
                        st.markdown(
                            f'<span class="below-budget">✅ Under target (${product["target"]:.2f})</span>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.caption(f"Target: ${product['target']:.2f}")
                if len(history) > 1:
                    st.line_chart(
                        {"price": [h["price"] for h in history]},
                        height=120,
                    )
                if st.button("Stop tracking", key=f"remove_{product['id']}"):
                    remove_product(product["id"])
                    st.rerun()

# Lightweight auto-refresh loop: reruns the script in place (same session,
# no browser navigation) once the interval elapses.
if auto and time.time() - st.session_state.last_refresh >= interval:
    refresh_all()
    st.rerun()
