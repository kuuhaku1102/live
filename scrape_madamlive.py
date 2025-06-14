import os
import json
import base64
import re
import time
from urllib.parse import urljoin

import gspread
from bs4 import BeautifulSoup

SPREADSHEET_ID = os.environ["SPREADSHEET_ID"]
SHEET_NAME = os.environ["SHEET_NAME"]
LISTING_URL = os.environ["LISTING_URL"]

def get_gspread_client():
    b64 = os.environ["GSHEET_JSON"]
    data = json.loads(base64.b64decode(b64).decode("utf-8"))
    return gspread.service_account_from_dict(data)

def open_sheet():
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(SHEET_NAME)

def fetch_html_playwright(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        # Actions上はGUIがないため必ずheadless=True
        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            extra_http_headers={
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Referer": "https://www.madamlive.tv/"
            }
        )
        print(f"Navigating to: {url}")
        page.goto(url, timeout=60000, wait_until="networkidle")
        time.sleep(2)
        html = page.content()
        browser.close()
        return html

def fetch_html_requests(url):
    import requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://www.madamlive.tv/"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def parse_listing(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for dl in soup.select("dl.onlinegirl-dl-big"):
        name_a = dl.select_one("dt.onlinegirl-dt-big h3 a")
        img_tag = dl.select_one("dd.onlinegirl-dd-img-big img")
        comment_tag = dl.select_one("dd.onlinegirl-dd-name-big span.onlinegirl-dd-comment-span-big a")
        if not (name_a and img_tag):
            continue
        name = name_a.contents[0].strip() if name_a.contents else name_a.get_text(strip=True)
        url = name_a.get("href", "")
        if url and not url.startswith("http"):
            url = urljoin(base_url, url)
        image = urljoin(base_url, img_tag.get("src", ""))
        comment = comment_tag.get_text(strip=True) if comment_tag else ""
        entries.append({
            "name": name,
            "image": image,
            "url": url,
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
    detail = {
        "年齢": get_dd("年齢"),
        "身長": get_dd("身長"),
        "スリーサイズ": get_dd("スリーサイズ"),
        "顔出し": get_dd("顔出し"),
        "おもちゃ": get_dd("おもちゃ"),
        "出没時間": get_dd("出没時間"),
        "スタイル": get_dd("スタイル"),
        "職業": get_dd("職業"),
        "趣味": get_dd("趣味"),
        "好みのタイプ": get_dd("好みのタイプ"),
        "性感帯": get_dd("性感帯"),
        "ジャンル": get_dd("ジャンル"),
    }
    return detail

def main():
    ws = open_sheet()
    existing = set(ws.col_values(3))  # C列（url）

    print(f"Fetching JS-rendered listing page: {LISTING_URL}")
    listing_html = fetch_html_playwright(LISTING_URL)
    if not listing_html:
        print("Failed to get listing page. Aborting.")
        return

    items = parse_listing(listing_html, LISTING_URL)
    print(f"Found {len(items)} items on the listing page.")

    for item in items:
        if item["url"] in existing:
            continue

        print(f"Fetching detail page: {item['url']}")
        detail_html = fetch_html_requests(item["url"])
        if not detail_html:
            print(f"Skipping {item['name']} because detail page could not be fetched.")
            continue

        detail = parse_detail(detail_html)
        row = [
            item["name"],                      # name
            item["image"],                     # samune
            item["url"],                       # url
            item["comment"],                   # oneword
            detail.get("年齢", ""),             # 年齢
            detail.get("身長", ""),             # 身長
            detail.get("スリーサイズ", ""),     # スリーサイズ
            detail.get("顔出し", ""),           # 顔出し
            detail.get("おもちゃ", ""),         # おもちゃ
            detail.get("出没時間", ""),         # 出没時間
            detail.get("スタイル", ""),         # スタイル
            detail.get("職業", ""),             # 職業
            detail.get("趣味", ""),             # 趣味
            detail.get("好みのタイプ", ""),     # 好みのタイプ
            detail.get("性感帯", ""),           # 性感帯
            detail.get("ジャンル", ""),         # ジャンル
        ]
        ws.append_row(row)
        print(f"Added: {item['name']} - {item['url']}")

        time.sleep(1.5
