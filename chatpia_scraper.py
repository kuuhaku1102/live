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
# Detail Page Parsing
# ---------------------------------------------------------
def extract_background_image(style: str, base_url: str) -> str:
    match = re.search(r"url\((.*?)\)", style or "")
    if not match:
        return ""
    return urljoin(base_url, match.group(1).strip("'\""))


def find_labeled_value(soup: BeautifulSoup, keywords: list[str]) -> str:
    def matches(tag):
        if not getattr(tag, "get_text", None):
            return False
        t = tag.get_text(strip=True)
        return any(k in t for k in keywords)

    label = soup.find(matches)
    if not label:
        return ""

    if label.name == "dt":
        dd = label.find_next_sibling("dd")
        return text_content(dd)

    if label.name == "th":
        td = label.find_next_sibling("td")
        return text_content(td)

    sib = label.find_next(lambda x: x is not label and x.name in {"dd", "td", "span", "div", "p", "li"})
    return text_content(sib)


def parse_detail_page(detail_url: str) -> dict:
    if not detail_url:
        return {k: "" for k in [
            "age", "height", "cup", "face_public",
            "toy", "time_slot", "style", "job",
            "hobby", "favorite_type", "erogenous_zone",
            "genre_detail",
        ]}

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

    label_map = {
        "age": ["年齢", "歳", "才"],
        "height": ["身長", "cm"],
        "cup": ["カップ", "バスト"],
        "face_public": ["顔出し", "公開"],
        "toy": ["おもちゃ", "玩具"],
        "time_slot": ["出没時間", "時間"],
        "style": ["スタイル"],
        "job": ["職業"],
        "hobby": ["趣味"],
        "favorite_type": ["好みのタイプ", "好きなタイプ"],
        "erogenous_zone": ["性感帯"],
    }

    container = soup.select_one(".profile, .cast-profile, .profile-box")

    if container:
        for dl in container.select("dl"):
            dt = dl.find("dt")
            dd = dl.find("dd")
            label = text_content(dt)
            val = text_content(dd)
            if not label:
                continue
            for key, keys in label_map.items():
                if any(k in label for k in keys):
                    fields[key] = val

        for table in container.select("table"):
            for tr in table.select("tr"):
                th = tr.find("th")
                td = tr.find("td")
                label = text_content(th)
                val = text_content(td)
                if not label:
                    continue
                for key, keys in label_map.items():
                    if any(k in label for k in keys):
                        fields[key] = val

        tags = [text_content(t) for t in container.select(".tag, .genre, .badge")]
        tags = [x for x in tags if x]
        if tags:
            fields["genre_detail"] = ", ".join(tags)

    fields["age"] = extract_age_digits(first_non_empty(
        fields["age"],
        find_labeled_value(soup, label_map["age"]),
    ))

    return fields


# ---------------------------------------------------------
# Card Extraction
# ---------------------------------------------------------
def extract_card_info(card, base_url: str) -> dict:
    name_el = card.select_one("div.name a, .name a, h3 a, h4 a")
    comment_el = card.select_one("div.hitokoto, div.hitokoto_new, .hitokoto, .hitokoto_new")
    raw_name = text_content(name_el)

    thumb = ""
    pic = card.select_one("div.pict[style], .pict[style]")
    if pic and pic.has_attr("style"):
        thumb = extract_background_image(pic["style"], base_url)

    link = name_el if name_el and name_el.has_attr("href") else card.find("a", href=True)
    detail_url = urljoin(base_url, link["href"]) if link else ""

    age_from_name = ""
    m = re.match(r"^(.*?)[（(]\s*(\d+)[^）)]*[）)]", raw_name)
    if m:
        name = m.group(1).strip()
        age_from_name = m.group(2)
    else:
        name = raw_name

    name = sanitize_profile_name(name)

    return {
        "name": name or "-",
        "samune": thumb or "-",
        "url": detail_url or "-",
        "oneword": text_content(comment_el) or "-",
        "age_from_name": age_from_name or "",
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
# Main Scraper
# ---------------------------------------------------------
def scrape_chatpia():
    env_base = os.environ.get("CHATPIA_BASE_URL", "").strip()
    base_url = env_base if env_base.startswith("http") else "https://www.chatpia.jp/main.php"

    html = fetch_html(base_url)
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select("div.line, div.chatbox-box, .line")
    if not cards:
        cards = soup.select("div")

    seen = set()
    items = []

    for card in cards:
        info = extract_card_info(card, base_url)

        if not info["url"].startswith("http"):
            continue
        if info["url"] in seen:
            continue
        seen.add(info["url"])

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
        if not item["url"].startswith("http"):
            print("Skipping invalid URL:", item["url"])
            continue

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


# ---------------------------------------------------------
if __name__ == "__main__":
    scrape_chatpia()
