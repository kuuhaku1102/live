import os
import json
import base64
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import gspread

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "fanza")
LISTING_URL = os.environ.get("LISTING_URL", "https://www.dmm.co.jp/live/chat/")
# Whether to use Playwright for fetching pages. Defaults to True because the
# listing page loads entries via JavaScript.
USE_PLAYWRIGHT = os.environ.get("USE_PLAYWRIGHT", "1") != "0"


def get_gspread_client():
    b64 = os.environ.get("GSHEET_JSON")
    if not b64:
        raise ValueError("GSHEET_JSON not set")
    data = json.loads(base64.b64decode(b64).decode("utf-8"))
    return gspread.service_account_from_dict(data)


def open_sheet():
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(SHEET_NAME)


def fetch_html(url, use_playwright=False):
    """Fetch a page and return its HTML."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/110.0 Safari/537.36"
        )
    }

    if not use_playwright:
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None

    # Fallback to playwright when JavaScript rendering is required.
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover - playwright may not be installed
        print(f"Playwright unavailable: {e}")
        return None

    try:
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.set_extra_http_headers(headers)
            page.goto(url)
            page.wait_for_load_state("networkidle")
            html = page.content()
            browser.close()
            return html
    except Exception as e:
        print(f"Playwright error fetching {url}: {e}")
        return None


def parse_listing(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for li in soup.select("li.CharacterItem"):
        anchor = li.select_one("a.CharacterItem__anchor")
        if not anchor:
            continue
        name_tag = li.select_one(".CharacterItem__name")
        name = name_tag.get_text(strip=True) if name_tag else ""
        url = anchor.get("href")
        if url and not url.startswith("http"):
            url = urljoin(base_url, url)
        img_tag = li.select_one("img.CharacterItem__img")
        img = img_tag.get("src") if img_tag else ""
        if img and not img.startswith("http"):
            img = urljoin(base_url, img)
        comment_tag = li.select_one(".CharacterItem__comment")
        comment = comment_tag.get_text(strip=True) if comment_tag else ""
        entries.append({"name": name, "url": url, "image": img, "comment": comment})
    return entries


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    data = {}
    for tr in soup.select("table.cg-data-set tr"):
        th = tr.select_one("th")
        td = tr.select_one("td")
        if not th or not td:
            continue
        key = th.get_text(strip=True)
        value = td.get_text(strip=True).lstrip("：")
        data[key] = value
    return data


def main():
    ws = open_sheet()
    existing_urls = set(ws.col_values(3))

    # The listing page loads its content dynamically, so we try Playwright first
    # and fall back to a simple request if Playwright is not available.
    listing_html = (
        fetch_html(LISTING_URL, use_playwright=USE_PLAYWRIGHT)
        or fetch_html(LISTING_URL)
    )
    if not listing_html:
        print("Failed to fetch listing page")
        return

    items = parse_listing(listing_html, LISTING_URL)
    print(f"Found {len(items)} entries")

    for item in items:
        if item["url"] in existing_urls:
            continue
        # Detail pages might also rely on JavaScript, so fall back to Playwright
        detail_html = (
            fetch_html(item["url"])
            or fetch_html(item["url"], use_playwright=USE_PLAYWRIGHT)
        )
        if not detail_html:
            print(f"Skipping {item['name']} - could not fetch detail")
            continue
        detail = parse_detail(detail_html)
        row = [
            item.get("name", ""),
            item.get("image", ""),
            item.get("url", ""),
            item.get("comment", ""),
            detail.get("ジャンル", ""),
            detail.get("身長", ""),
            detail.get("スリーサイズ", ""),
            detail.get("誕生日", ""),
            detail.get("血液型", ""),
            detail.get("地域", ""),
            detail.get("職業", ""),
            detail.get("特徴", ""),
            detail.get("タイプ", ""),
            detail.get("趣味", ""),
            detail.get("性格", ""),
            detail.get("似てる人", ""),
        ]
        ws.append_row(row)
        print(f"Added {item['name']}")
        time.sleep(1.5)


if __name__ == "__main__":
    main()
