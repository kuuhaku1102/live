import os
import re
from urllib.parse import urljoin

import requests
from requests import RequestException
from bs4 import BeautifulSoup

API_URL = os.environ.get("API_URL")
API_KEY = os.environ.get("API_KEY")

# -------------------------------------------
# Chatpia は UA + Referer + Cookie がほぼ必須
# -------------------------------------------
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.chatpia.jp/",
}


# ---------------------------------------------------------
# Basic Functions
# ---------------------------------------------------------
def make_session() -> requests.Session:
    """
    Chatpia 対策：
    - 1回目アクセスでCookieセット
    - 2回目アクセスで一覧HTML取得
    """
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)

    # GitHub Actions 環境変数で proxy を無効化するか選択
    trust_env = os.environ.get("CHATPIA_TRUST_ENV_PROXIES", "0") not in {
        "0",
        "false",
        "False",
        "",
    }
    s.trust_env = trust_env
    if not trust_env:
        s.proxies = {}
    return s


def fetch_html(url: str) -> str:
    session = make_session()

    # 1回目：トップアクセスで Cookie を付ける（失敗しても無視）
    try:
        session.get("https://www.chatpia.jp/", timeout=20)
    except Exception:
        pass

    # 2回目：本命ページ
    resp = session.get(url, timeout=25)
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
    # 記号を削除して、名前として使える部分だけ残す
    cleaned = re.sub(r"[^\w\sぁ-ゟ゠-ヿ一-龥々ー０-９Ａ-Ｚａ-ｚー-]+", "", name)
    return cleaned.strip()


# ---------------------------------------------------------
# Chatpia: 一覧カードから情報取得
# ---------------------------------------------------------
def extract_card_info(card, base_url: str) -> dict:
    """
    一覧の1カードから:
    - name
    - url
    - samune（サムネ）
    - oneword（ひとこと）
    - age_from_name（年齢）
    を取り出す
    """
    # 名前 + URL
    name_el = card.select_one(".name a")
    raw_name = text_content(name_el)

    # (53歳) などの年齢表記を名前から除外
    raw_name_no_age = re.sub(r"\(.*?\)", "", raw_name).strip()
    name = sanitize_profile_name(raw_name_no_age)

    # 詳細URL
    detail_url = ""
    if name_el and name_el.has_attr("href"):
        detail_url = urljoin(base_url, name_el["href"])

    # サムネ背景画像
    thumb = ""
    pict_el = card.select_one(".pict")
    if pict_el and pict_el.has_attr("style"):
        m = re.search(r"url\((.*?)\)", pict_el["style"])
        if m:
            raw = m.group(1).strip("'\"")
            # //picture.chatpia.jp/... の場合は https: を補う
            if raw.startswith("//"):
                raw = f"https:{raw}"
            thumb = raw

    # ひとこと
    comment_el = card.select_one(".hitokoto, .hitokoto_taiki, .hitokoto_new")
    oneword = text_content(comment_el)

    # 年齢（nameブロック内のテキストから数字だけ抜く）
    age_from_name = ""
    name_block = card.select_one(".name")
    if name_block:
        age_match = re.search(r"(\d+)", text_content(name_block))
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
# Chatpia: プロフィール詳細ページから情報取得
# ---------------------------------------------------------
def parse_detail_page(detail_url: str) -> dict:
    """
    プロフィール詳細から:
    - height（身長）
    - cup（カップ）
    - job（職業）
    - hobby（趣味）
    - favorite_type（男性のタイプ）
    - time_slot（出没時間）
    などを取得
    """
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

    html = fetch_html(detail_url)
    soup = BeautifulSoup(html, "html.parser")

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
        "genre_detail": "",
    }

    # Chatpia 詳細プロフィールは <section class="life-status"> 内
    section = soup.select_one("section.life-status")
    if not section:
        return fields

    # dt: 項目名, dd: 値
    dts = section.select("dt.life-status-detail__title")
    dds = section.select("dd.life-status-detail__data")

    for dt, dd in zip(dts, dds):
        label = text_content(dt)
        val = text_content(dd)

        if "身長" in label:
            fields["height"] = val  # 例: "158cm"

        elif "スリーサイズ" in label:
            # 例: "B(Dカップ) W H" から "Dカップ" を取りたい
            m = re.search(r"([A-ZＡ-Ｚ])カップ", val)
            if m:
                fields["cup"] = f"{m.group(1)}カップ"
            else:
                # テキスト全体を一旦入れておく
                fields["cup"] = val

        elif "職業" in label:
            fields["job"] = val

        elif "趣味" in label:
            fields["hobby"] = val

        elif "男性のタイプ" in label:
            fields["favorite_type"] = val

        elif "出没時間" in label:
            fields["time_slot"] = val

        # 必要ならここに「性感帯」「スタイル」なども追加でマッピング可能

    # ジャンルは Chatpia 固定でよければこれでOK
    fields["genre_detail"] = "Chatpia"

    return fields


# ---------------------------------------------------------
# Fallbacks
# ---------------------------------------------------------
def fill_with_dash(item: dict) -> dict:
    """
    name / samune / oneword / url 以外は "-" で埋めてOKな前提。
    ここでは全体を一旦 "-" 補完している。
    """
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

    # 一覧のカード候補
    cards = soup.select("div.chatbox_big, div.chatbox_small")
    if not cards:
        # 予備: 何かしら構造が変わった時用
        cards = soup.select("div.chatbox_big, div.chatbox-box, div.line")

    seen_urls = set()
    items = []

    for card in cards:
        info = extract_card_info(card, base_url)

        # サムネ & ひとことは必須（あなたの条件）
        if not info["samune"] or not info["oneword"]:
            continue

        # URL が不正ならスキップ
        if not info["url"].startswith("http"):
            continue
        if info["url"] in seen_urls:
            continue
        seen_urls.add(info["url"])

        # プロフィール詳細ページ解析
        try:
            detail = parse_detail_page(info["url"])
        except Exception as exc:
            print(f"Detail fetch failed for {info['url']}: {exc}")
            detail = {}

        item = {
            "name": info["name"],
            "samune": info["samune"],
            "url": info["url"],
            "oneword": info["oneword"],
            # age: 一覧の name ブロック側から取れた値を優先
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
