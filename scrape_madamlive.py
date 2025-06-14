import os
import json
import base64
import re
from urllib.parse import urljoin
import time

import requests
from bs4 import BeautifulSoup
import gspread

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "madam")
LISTING_URL = os.environ.get("LISTING_URL", "https://madamlive.tv/listing")


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


def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None


def parse_listing(html, base_url):
    """Parse madamlive listing page."""
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for a in soup.select("a[href]"):
        name = a.get_text(strip=True)
        img_tag = a.find("img")
        if not name or not img_tag:
            continue
        url = a.get("href", "")
        if url and not url.startswith("http"):
            url = urljoin(base_url, url)
        img = urljoin(base_url, img_tag.get("src", ""))
        comment = ""
        comment_tag = a.find(class_=re.compile("oneword|comment"))
        if comment_tag:
            comment = comment_tag.get_text(strip=True)
        entries.append({
            "name": name,
            "url": url,
            "image": img,
            "comment": comment,
        })
    return entries


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")

    def get_dd(label):
        dt = soup.find("dt", string=re.compile(label))
        if not dt:
            return ""
        dd = dt.find_next("dd")
        return dd.get_text(strip=True) if dd else ""

    mapping = {
        "age": "年齢",
        "height": "身長",
        "cup": "カップ数",
        "face": "顔出し",
        "toy": "おもちゃ",
        "appear": "出没時間",
        "style": "スタイル",
        "job": "職業",
        "hobby": "趣味",
        "favor": "好みのタイプ",
        "seikantai": "性感帯",
        "genre": "ジャンル",
    }

    detail = {}
    for key, label in mapping.items():
        detail[key] = get_dd(label)
    return detail


def main():
    ws = open_sheet()
    existing = set(ws.col_values(3))  # column C for URL

    print(f"Fetching listing page: {LISTING_URL}")
    listing_html = fetch_html(LISTING_URL)
    if not listing_html:
        print("Failed to get listing page. Aborting.")
        return

    items = parse_listing(listing_html, LISTING_URL)
    print(f"Found {len(items)} items on the listing page.")

    for item in items:
        if item["url"] in existing:
            continue

        print(f"Fetching detail page: {item['url']}")
        detail_html = fetch_html(item["url"])
        if not detail_html:
            print(f"Skipping {item['name']} because detail page could not be fetched.")
            continue

        detail = parse_detail(detail_html)
        row = [
            item["name"],
            item["image"],
            item["url"],
            item["comment"],
            detail.get("age", ""),
            detail.get("height", ""),
            detail.get("cup", ""),
            detail.get("face", ""),
            detail.get("toy", ""),
            detail.get("appear", ""),
            detail.get("style", ""),
            detail.get("job", ""),
            detail.get("hobby", ""),
            detail.get("favor", ""),
            detail.get("seikantai", ""),
            detail.get("genre", ""),
        ]
        ws.append_row(row)
        print(f"Added: {item['name']} - {item['url']}")

        time.sleep(1.5)


if __name__ == "__main__":
    main()
