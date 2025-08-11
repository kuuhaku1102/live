import os
import json
import base64
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import gspread

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID")
SHEET_NAME     = os.environ.get("SHEET_NAME", "live")
LISTING_URL    = os.environ.get("LISTING_URL", "https://example.com/listing")

HEADERS = [
    "name","samune","url","oneword",
    "年齢","身長","カップ数","顔出し",
    "おもちゃ","出没時間","スタイル","職業",
    "趣味","好みのタイプ","性感帯","ジャンル"
]  # A1:P1 に入る16列


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


def ensure_headers(ws):
    """A1:P1 にヘッダーを敷く。W1に『投稿済み』等があってもOK。"""
    try:
        current = ws.row_values(1)
    except Exception:
        current = []
    needs_update = (len(current) < len(HEADERS)) or (current[:len(HEADERS)] != HEADERS)
    if needs_update:
        ws.update('A1:P1', [HEADERS])


def fetch_html(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/108.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None


def parse_listing(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for a in soup.select("a[href]"):
        if not a.select_one("h3 > b.bold"):
            continue
        name = a.select_one("h3 > b.bold").get_text(strip=True)
        url = a["href"]
        if not url.startswith("http"):
            url = urljoin(base_url, url)

        img = ""
        img_span = a.select_one("li.image span[style]")
        if img_span:
            m = re.search(r"url\((.*?)\)", img_span.get("style", ""))
            if m:
                img = urljoin(base_url, m.group(1).strip("'\""))

        comment = ""
        comment_tag = a.select_one("li.taiki_comment")
        if comment_tag:
            comment = comment_tag.get_text(strip=True)

        entries.append({"name": name, "url": url, "image": img, "comment": comment})
    return entries


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")

    def text(sel):
        tag = soup.select_one(sel)
        return tag.get_text(strip=True) if tag else ""

    detail = {
        "age":       text("dd.p-age"),
        "height":    text("dd.p-height"),
        "cup":       text("dd.p-cup"),
        "face":      text("dd.p-face"),
        "toy":       text("dd.p-toy"),
        "appear":    text("dd.p-appear"),
        "style":     text("dd.p-style"),
        "job":       text("dd.p-job"),
        "hobby":     text("dd.p-hobby"),
        "favor":     text("dd.p-favor"),
        "seikantai": text("dd.p-seikantai"),
    }
    genres = [div.get_text(strip=True) for div in soup.select("dd.genre-list div.genre-div")]
    detail["genre"] = ",".join(genres)
    return detail


def main():
    ws = open_sheet()

    # ① 必ず A1:P1 にヘッダーを敷く（W1に文字があっても問題なし）
    ensure_headers(ws)

    # ② 既存URL（C列）を取得
    existing = set(ws.col_values(3))  # 3 = C列 (url)

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
            detail["age"],
            detail["height"],
            detail["cup"],
            detail["face"],
            detail["toy"],
            detail["appear"],
            detail["style"],
            detail["job"],
            detail["hobby"],
            detail["favor"],
            detail["seikantai"],
            detail["genre"],
        ]

        # ③ 追記時は必ず A1:P1 をテーブル起点に指定（←これが肝）
        ws.append_row(
            row,
            value_input_option="USER_ENTERED",
            table_range="A1:P1"   # ★ ここを指定することでW列起点問題を回避
        )
        print(f"Added: {item['name']} - {item['url']}")

        # 相手サーバー配慮
        time.sleep(1.5)


if __name__ == "__main__":
    main()
