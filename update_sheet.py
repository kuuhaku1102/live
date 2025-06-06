import os
import json
import base64
import re
from urllib.parse import urljoin
import time  ### 変更点：timeモジュールをインポート

import requests
from bs4 import BeautifulSoup
import gspread

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "live")
LISTING_URL = os.environ.get("LISTING_URL", "https://example.com/listing")


def get_gspread_client():
    b64 = os.environ.get("GSHEET_JSON")
    if not b64:
        raise ValueError("GSHEET_JSON not set")
    data = json.loads(base64.b64decode(b64).decode('utf-8'))
    return gspread.service_account_from_dict(data)


def open_sheet():
    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    return sh.worksheet(SHEET_NAME)


### 変更点：fetch_html関数を修正 ###
def fetch_html(url):
    # ブラウザからのアクセスを装うためのヘッダー情報
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
    }
    try:
        # ヘッダー情報を付けてアクセスし、タイムアウトを20秒に設定
        resp = requests.get(url, headers=headers, timeout=20)
        # 正常なレスポンス（200 OKなど）以外の場合はエラーを発生させる
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.RequestException as e:
        # 接続エラーやタイムアウトなどが発生した場合は、エラーメッセージを表示してNoneを返す
        print(f"Error fetching {url}: {e}")
        return None


def parse_listing(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')
    entries = []
    for a in soup.select('a[href]'):
        if not a.select_one('h3 > b.bold'):
            continue
        name = a.select_one('h3 > b.bold').get_text(strip=True)
        url = a['href']
        if not url.startswith('http'):
            url = urljoin(base_url, url)
        img = ''
        img_span = a.select_one('li.image span[style]')
        if img_span:
            m = re.search(r"url\((.*?)\)", img_span['style'])
            if m:
                img = urljoin(base_url, m.group(1).strip("'\""))
        comment = ''
        comment_tag = a.select_one('li.taiki_comment')
        if comment_tag:
            comment = comment_tag.get_text(strip=True)
        entries.append({'name': name, 'url': url, 'image': img, 'comment': comment})
    return entries


def parse_detail(html):
    soup = BeautifulSoup(html, 'html.parser')

    def text(sel):
        tag = soup.select_one(sel)
        return tag.get_text(strip=True) if tag else ''

    detail = {
        'age': text('dd.p-age'),
        'height': text('dd.p-height'),
        'cup': text('dd.p-cup'),
        'face': text('dd.p-face'),
        'toy': text('dd.p-toy'),
        'appear': text('dd.p-appear'),
        'style': text('dd.p-style'),
        'job': text('dd.p-job'),
        'hobby': text('dd.p-hobby'),
        'favor': text('dd.p-favor'),
        'seikantai': text('dd.p-seikantai'),
    }
    genres = [div.get_text(strip=True) for div in soup.select('dd.genre-list div.genre-div')]
    detail['genre'] = ','.join(genres)
    return detail


def main():
    ws = open_sheet()
    existing = set(ws.col_values(3))  # column C
    
    print(f"Fetching listing page: {LISTING_URL}")
    listing_html = fetch_html(LISTING_URL)
    if not listing_html:
        print("Failed to get listing page. Aborting.")
        return

    items = parse_listing(listing_html, LISTING_URL)
    print(f"Found {len(items)} items on the listing page.")

    for item in items:
        if item['url'] in existing:
            continue
            
        print(f"Fetching detail page: {item['url']}")
        detail_html = fetch_html(item['url'])
        
        ### 変更点：詳細ページの取得に失敗した場合の処理を追加 ###
        if not detail_html:
            print(f"Skipping {item['name']} because detail page could not be fetched.")
            continue

        detail = parse_detail(detail_html)
        row = [
            item['name'],
            item['image'],
            item['url'],
            item['comment'],
            detail['age'],
            detail['height'],
            detail['cup'],
            detail['face'],
            detail['toy'],
            detail['appear'],
            detail['style'],
            detail['job'],
            detail['hobby'],
            detail['favor'],
            detail['seikantai'],
            detail['genre'],
        ]
        ws.append_row(row)
        print(f"Added: {item['name']} - {item['url']}")
        
        ### 変更点：相手サーバーに配慮し、1.5秒待機する ###
        time.sleep(1.5)


if __name__ == '__main__':
    main()
