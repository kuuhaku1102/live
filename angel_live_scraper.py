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


def make_session() -> requests.Session:
    session = requests.Session()
    trust_env = os.environ.get("ANGEL_LIVE_TRUST_ENV_PROXIES", "0") not in {
        "0", "false", "False", ""
    }
    session.trust_env = trust_env
    if not trust_env:
        session.proxies = {}
    return session


def fetch_html(url: str) -> str:
    session = make_session()
    resp = session.get(url, headers=DEFAULT_HEADERS, timeout=20)
    resp.raise_for_status()

    if resp.apparent_encoding:
        resp.encoding = resp.apparent_encoding

    return resp.text


def text_content(tag) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


def first_non_empty(*values: str) -> str:
    for value in values:
        if value:
            return value
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


def extract_background_image(style: str, base_url: str) -> str:
    match = re.search(r"url\((.*?)\)", style or "")
    if not match:
        return ""
    return urljoin(base_url, match.group(1).strip("'\""))


def find_labeled_value(soup: BeautifulSoup, keywords: list[str]) -> str:
    def matches(tag):
        if not getattr(tag, "get_text", None):
            return False
        text = tag.get_text(strip=True)
        return any(key in text for key in keywords)

    label = soup.find(matches)
    if not label:
        return ""

    if label.name == "dt":
        sibling = label.find_next_sibling("dd")
        if sibling:
            return text_content(sibling)

    if label.name == "th":
        sibling = label.find_next_sibling("td")
        if sibling:
            return text_content(sibling)

    sibling = label.find_next(lambda tag: tag is not label and tag.name in {"dd", "td", "span", "div", "p", "li"})
    return text_content(sibling)


def parse_detail_page(detail_url: str) -> dict:
    if not detail_url:
        return {k: "" for k in [
            "age", "height", "cup", "face_public",
            "toy", "time_slot", "style", "job",
            "hobby", "favorite_type", "erogenous_zone", "genre_detail"
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
        "face_public": ["顔出し", "顔", "公開"],
        "toy": ["おもちゃ", "玩具"],
        "time_slot": ["出没時間", "時間"],
        "style": ["スタイル"],
        "job": ["職業"],
        "hobby": ["趣味"],
        "favorite_type": ["好みのタイプ", "好きなタイプ"],
        "erogenous_zone": ["性感帯"],
    }

    profile_container = soup.select_one(".profile, .cast-profile, .profile-box")

    if profile_container:
        for dl in profile_container.select("dl"):
            dt = dl.find("dt")
            dd = dl.find("dd")
            label = text_content(dt)
            value = text_content(dd)
            if not label:
                continue
            for field, keywords in label_map.items():
                if any(key in label for key in keywords):
                    fields[field] = value

        for table in profile_container.select("table"):
            for row in table.select("tr"):
                th = row.find("th")
                td = row.find("td")
                label = text_content(th)
                value = text_content(td)
                if not label:
                    continue
                for field, keywords in label_map.items():
                    if any(key in label for key in keywords):
                        fields[field] = value

        genre_tags = [text_content(tag) for tag in profile_container.select(".tag, .genre, .badge")]
        genre_tags = [g for g in genre_tags if g]
        if genre_tags:
            fields["genre_detail"] = ", ".join(genre_tags)

    selectors = {
        "age": [".age", "span.age", "li.age", "td.age"],
        "height": [".height", "span.height", "li.height", "td.height"],
        "cup": [".cup", "span.cup", "li.cup", "td.cup"],
        "face_public": [".face", "span.face", "li.face", "td.face"],
    }

    def pick_from_selector(key: str) -> str:
        for sel in selectors[key]:
            tag = soup.select_one(sel)
            if tag and text_content(tag):
                return text_content(tag)
        return ""

    fields["age"] = extract_age_digits(first_non_empty(fields["age"], pick_from_selector("age"), find_labeled_value(soup, label_map["age"])))
    fields["height"] = first_non_empty(fields["height"], pick_from_selector("height"), find_labeled_value(soup, label_map["height"]))

    return fields


def extract_card_info(card, base_url: str) -> dict:
    name_el = card.select_one("h3.girl-prof__name, .girl-prof__name, h3, h4")
    comment_el = card.select_one("div.girl-comment p.girl-comment__txt, .girl-comment__txt")

    thumb = ""
    style_holder = card.select_one(".girl-pic__image[style]")
    if style_holder and style_holder.has_attr("style"):
        thumb = extract_background_image(style_holder["style"], base_url)

    detail_link = card.select_one("a.girl-link[href]") or card.find("a", href=True)
    detail_url = urljoin(base_url, detail_link["href"]) if detail_link else ""

    raw_name = text_content(name_el)
    name = raw_name
    age_from_name = ""

    name_age_match = re.match(r"^(.*?)[（(]\s*(\d+)[^）)]*[）)]", raw_name)
    if name_age_match:
        name = name_age_match.group(1).strip()
        age_from_name = name_age_match.group(2)

    name = sanitize_profile_name(name)

    return {
        "name": name or "-",
        "samune": thumb or "-",
        "url": detail_url or "-",
        "oneword": text_content(comment_el) or "-",
        "age_from_name": age_from_name or "",
    }


def fill_missing_with_dash(item: dict) -> dict:
    """
    必須項目以外は "-" を許容
    """
    for key, value in item.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            item[key] = "-"
    return item


def scrape_angel():
    base_url = os.environ.get("ANGEL_LIVE_BASE_URL", "https://www.angel-live.com/home/").strip()

    html = fetch_html(base_url)
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select("li.girl-line__item, li.girl-line__item.chatbox_big, li.girl-line__item.chatbox_big.event_now")
    if not cards:
        cards = soup.select("li.girl-line__item") or soup.select("li")

    seen = set()
    items = []

    for card in cards:
        info = extract_card_info(card, base_url)

        detail_url = info.get("url")
        if not detail_url or detail_url in seen or detail_url == "-":
            continue
        seen.add(detail_url)

        try:
            detail_fields = parse_detail_page(detail_url)
        except Exception as exc:
            print(f"Detail fetch failed for {detail_url}: {exc}")
            detail_fields = {}

        item = {
            "name": info["name"],
            "samune": info["samune"],
            "url": detail_url,
            "oneword": info["oneword"],
            "age": extract_age_digits(first_non_empty(detail_fields.get("age", ""), info.get("age_from_name", ""))) or "-",
            "height": detail_fields.get("height", "") or "-",
            "cup": detail_fields.get("cup", "") or "-",
            "face_public": detail_fields.get("face_public", "") or "-",
            "toy": detail_fields.get("toy", "") or "-",
            "time_slot": detail_fields.get("time_slot", "") or "-",
            "style": detail_fields.get("style", "") or "-",
            "job": detail_fields.get("job", "") or "-",
            "hobby": detail_fields.get("hobby", "") or "-",
            "favorite_type": detail_fields.get("favorite_type", "") or "-",
            "erogenous_zone": detail_fields.get("erogenous_zone", "") or "-",
            "genre": detail_fields.get("genre_detail", "") or "Angel Live",
        }

        fill_missing_with_dash(item)
        items.append(item)

    headers = {"X-API-KEY": API_KEY}
    success_count = 0

    for item in items:

        # URL が正しくない場合は送信しない（必須・一意）
        if not item["url"].startswith("http"):
            print("Skipping invalid URL:", item["name"], item["url"])
            continue

        try:
            r = requests.post(API_URL, json=item, headers=headers, timeout=20)
            r.raise_for_status()
            success_count += 1
            print("Posted:", item["name"], r.text)
        except RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", "no-status")
            body = getattr(getattr(exc, "response", None), "text", "")
            print(f"Post failed for {item.get('name')} (status={status}): {exc}. Body: {body}")

    print("完了：Angel Live 送信数 →", success_count)


if __name__ == "__main__":
    scrape_angel()
