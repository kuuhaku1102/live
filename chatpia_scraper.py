import os
import re
from urllib.parse import urljoin
import requests
from requests import RequestException
from bs4 import BeautifulSoup

API_URL = os.environ.get("API_URL")
API_KEY = os.environ.get("API_KEY")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------
# Basic Functions
# ---------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    trust_env = os.environ.get("CHATPIA_TRUST_ENV_PROXIES", "0") not in {
        "0", "false", "False", "",
    }
    s.trust_env = trust_env
    if not trust_env:
        s.proxies = {}
    return s


def fetch_html(url: str) -> str:
    session = make_session()
    resp = session.get(url, headers=DEFAULT_HEADERS, timeout=20)
    resp.raise_for_status()

    if resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding

    return resp.text


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


# ---------------------------------------------------------
# Chatpia: Extract Card Info
# ---------------------------------------------------------
def extract_card_info(card, base_url: str) -> dict:
    # ----------------------
    # 名前
    # ----------------------
    name_el = card.select_one(".name a")
    raw_name = text_content(name_el)

    # 年齢span削除 → "kiyomi"
    raw_name = re.sub(r"\(.*?\)", "", raw_name).strip()

    name = sanitize_profile_name(raw_name)

    # ----------------------
    # 詳細URL（必須）
    # ----------------------
    detail_url = ""
    if name_el and name_el.has_attr("href"):
        detail_url = urljoin(base_url, name_el["href"])

    # ----------------------
    # サムネ背景画像
    # ----------------------
    thumb = ""
    pict_el = card.select_one(".pict")
    if pict_el and pict_el.has_attr("style"):
        m = re.search(r"url\((.*?)\)", pict_el["style"])
        if m:
            thumb = m.group(1).strip("'\"")

    # ----------------------
    # ひとこと
    # ----------------------
    comment_el = card.select_one(".hitokoto, .hitokoto_taiki, .hitokoto_new")
    oneword = text_content(comment_el)

    # ----------------------
    # 年齢抽出
    # ----------------------
    age_from_name = ""
    age_match = re.search(r"(\d+)", text_content(card.select_one(".name")))
    if age_match:
        age_from_name = age_match.group(1)

    return {
        "name": name or "-",
        "samune": thumb or "",
        "url": detail_url or "",
        "oneword": oneword or "",
        "age_from_name": age_from_name or "",
    }


# ---------------------------------------------------------
# Detail Page Parsing（Chatpiaは詳細ページ情報が少ない）
# ---------------------------------------------------------
def parse_detail_page(detail_url: str) -> dict:
    # Chatpiaは詳細の構造がバラバラ → 基本空でOK
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


# ---------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------
def fill_with_dash(item: dict) -> dict:
    for k, v in item.items():
        if v is None or (isinstance(v, str) and not v.strip()):
            item[k] = "-"
    return item


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
def scrape_chatpia():
    env_base = os.environ.get("CHATPIA_BASE_URL", "").strip()
    base_url = env_base if env_base.startswith("http") else "https://www.chatpia.jp/main.php"

    html = fetch_html(base_url)
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select("div.chatbox_big, div.chatbox_small, div.chatbox-box, div.line")
    if not cards:
        cards = soup.select("div")

    seen = set()
    items = []

    for card in cards:
        info = extract_card_info(card, base_url)

        # サムネ or 一言が取れなかったらスキップ（必須）
        if not info["samune"] or not info["oneword"]:
            continue

        # URL必須
        if not info["url"].startswith("http"):
            continue
        if info["url"] in seen:
            continue
        seen.add(info["url"])

        detail = parse_detail_page(info["url"])

        item = {
            "name": info["name"],
            "samune": info["samune"],
            "url": info["url"],
            "oneword": info["oneword"],
            "age": extract_age_digits(first_non_empty(detail.get("age", ""), info.get("age_from_name"))) or "-",
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

    headers = {"X-API-KEY": API_KEY}
    success = 0

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
