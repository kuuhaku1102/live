import os
import re
from urllib.parse import urljoin

import requests
from requests import RequestException
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

API_URL = os.environ.get("API_URL")
API_KEY = os.environ.get("API_KEY")

BASE_URL = os.environ.get("CHATPIA_BASE_URL", "https://www.chatpia.jp/main.php").strip() or "https://www.chatpia.jp/main.php"

# ブラウザ用ヘッダー
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.chatpia.jp/",
}


def text_content(tag) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


def first_non_empty(*vals):
    for v in vals:
        if v:
            return v
    return ""


def extract_age_digits(value: str) -> str:
    if not value:
        return ""
    m = re.search(r"(\d+)", value)
    return m.group(1) if m else ""


def sanitize_profile_name(name: str) -> str:
    if not name:
        return ""
    cleaned = re.sub(r"[^\w\sぁ-ゟ゠-ヿ一-龥々ー０-９Ａ-Ｚａ-ｚー-]+", "", name)
    return cleaned.strip()


# ---------------------- 一覧カード ----------------------
def extract_card_info(card, base_url: str) -> dict:
    # 名前
    name_el = card.select_one(".name a")
    raw_name = text_content(name_el)
    raw_name_no_age = re.sub(r"\(.*?\)", "", raw_name).strip()
    name = sanitize_profile_name(raw_name_no_age)

    # URL
    detail_url = ""
    if name_el and name_el.has_attr("href"):
        detail_url = urljoin(base_url, name_el["href"])

    # サムネ
    thumb = ""
    pict_el = card.select_one(".pict")
    if pict_el and pict_el.has_attr("style"):
        m = re.search(r"url\((.*?)\)", pict_el["style"])
        if m:
            raw = m.group(1).strip("'\"")
            if raw.startswith("//"):
                raw = f"https:{raw}"
            thumb = raw

    # ひとこと
    comment_el = card.select_one(".hitokoto, .hitokoto_taiki, .hitokoto_new")
    oneword = text_content(comment_el)

    # 年齢
    age_from_name = ""
    name_block = card.select_one(".name")
    if name_block:
        m = re.search(r"(\d+)", text_content(name_block))
        if m:
            age_from_name = m.group(1)

    return {
        "name": name or "-",
        "samune": thumb or "",
        "url": detail_url or "",
        "oneword": oneword or "",
        "age_from_name": age_from_name or "",
    }


# ---------------------- 詳細プロフィール ----------------------
def parse_detail_page(detail_url: str) -> dict:
    if not detail_url:
        return {
            "age": "",
            "height": "",
            "cup": "",
            "face_public": "",
            "toy": "",
            "time_slot": "",
            "style": "",
            "job": "",
            "hobby": "",
            "favorite_type": "",
            "erogenous_zone": "",
            "genre_detail": "",
        }

    # requests で詳細ページを取得（ここもPlaywrightにしたいなら差し替え可）
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    resp = session.get(detail_url, timeout=20)
    resp.raise_for_status()
    if resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding

    soup = BeautifulSoup(resp.text, "html.parser")

    fields = {
        "age": "",
        "height": "",
        "cup": "",
        "face_public": "",
        "toy": "",
        "time_slot": "",
        "style": "",
        "job": "",
        "hobby": "",
        "favorite_type": "",
        "erogenous_zone": "",
        "genre_detail": "Chatpia",
    }

    section = soup.select_one("section.life-status")
    if not section:
        return fields

    dts = section.select("dt.life-status-detail__title")
    dds = section.select("dd.life-status-detail__data")

    for dt, dd in zip(dts, dds):
        label = text_content(dt)
        val = text_content(dd)

        if "身長" in label:
            fields["height"] = val
        elif "スリーサイズ" in label:
            m = re.search(r"([A-ZＡ-Ｚ])カップ", val)
            fields["cup"] = m.group(0) if m else val
        elif "職業" in label:
            fields["job"] = val
        elif "趣味" in label:
            fields["hobby"] = val
        elif "男性のタイプ" in label:
            fields["favorite_type"] = val
        elif "出没時間" in label:
            fields["time_slot"] = val

    return fields


def fill_with_dash(item: dict) -> dict:
    for k, v in item.items():
        if v is None or (isinstance(v, str) and not v.strip()):
            item[k] = "-"
    return item


# ---------------------- メイン処理 ----------------------
def scrape_chatpia():
    success = 0
    items = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=DEFAULT_HEADERS["User-Agent"],
            locale="ja-JP",
            extra_http_headers={
                "Accept-Language": DEFAULT_HEADERS["Accept-Language"],
                "Referer": DEFAULT_HEADERS["Referer"],
            },
        )
        page = context.new_page()
        page.goto(BASE_URL, wait_until="networkidle", timeout=30000)

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        cards = soup.select("div.chatbox_big, div.chatbox_small")
        if not cards:
            cards = soup.select("div.chatbox-box, .line")

        seen_urls = set()

        for card in cards:
            info = extract_card_info(card, BASE_URL)

            # 必須：サムネ & 一言 & URL
            if not info["samune"] or not info["oneword"]:
                continue
            if not info["url"].startswith("http"):
                continue
            if info["url"] in seen_urls:
                continue
            seen_urls.add(info["url"])

            # 詳細ページ解析
            try:
                detail = parse_detail_page(info["url"])
            except Exception as exc:
                print(f"Detail fetch error for {info['url']}: {exc}")
                detail = {}

            item = {
                "name": info["name"],
                "samune": info["samune"],
                "url": info["url"],
                "oneword": info["oneword"],
                "age": extract_age_digits(
                    first_non_empty(detail.get("age", ""), info.get("age_from_name"))
                ) or "-",
                "height": detail.get("height", "") or "-",
                "cup": detail.get("cup", "") or "-",
                "face_public": detail.get("face_public", "") or "-",
                "toy": detail.get("toy", "") or "-",
                "time_slot": detail.get("time_slot", "") or "-",
                "style": detail.get("style", "") or "-",
                "job": detail.get("job", "") or "-",
                "hobby": detail.get("hobby", "") or "-",
                "favorite_type": detail.get("favorite_type", "") or "-",
                "erogenous_zone": detail.get("erogenous_zone", "") or "-",
                "genre": detail.get("genre_detail", "") or "Chatpia",
            }

            fill_with_dash(item)
            items.append(item)

        browser.close()

    # API送信
    headers = {"X-API-KEY": API_KEY}
    for item in items:
        try:
            r = requests.post(API_URL, json=item, headers=headers, timeout=20)
            r.raise_for_status()
            success += 1
            print("Posted:", item["name"], r.text)
        except RequestException as exc:
            status = getattr(exc.response, "status_code", "no-status")
            body = getattr(exc.response, "text", "")
            print(f"Post failed for {item['name']} (status={status}): {body}")

    print("完了：Chatpia 送信数 →", success)


if __name__ == "__main__":
    scrape_chatpia()
