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
    """Create a session that optionally ignores proxy env vars."""

    session = requests.Session()
    trust_env = os.environ.get("ANGEL_LIVE_TRUST_ENV_PROXIES", "0") not in {
        "0",
        "false",
        "False",
        "",
    }
    session.trust_env = trust_env
    if not trust_env:
        session.proxies = {}
    return session


def fetch_html(url: str) -> str:
    session = make_session()
    resp = session.get(url, headers=DEFAULT_HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def text_content(tag) -> str:
    return tag.get_text(" ", strip=True) if tag else ""


def first_non_empty(*values: str) -> str:
    for value in values:
        if value:
            return value
    return ""


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

    sibling = label.find_next(
        lambda tag: tag is not label and tag.name in {"dd", "td", "span", "div", "p", "li"}
    )
    return text_content(sibling)


def parse_detail_page(detail_url: str) -> dict:
    """Parse detail page fields from Angel Live profiles."""

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
                    break

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
                        break

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

    def pick_from_selectors(key: str) -> str:
        for sel in selectors[key]:
            tag = soup.select_one(sel)
            if tag and text_content(tag):
                return text_content(tag)
        return ""

    fields["age"] = first_non_empty(fields["age"], pick_from_selectors("age"), find_labeled_value(soup, label_map["age"]))
    fields["height"] = first_non_empty(
        fields["height"], pick_from_selectors("height"), find_labeled_value(soup, label_map["height"])
    )
    fields["cup"] = first_non_empty(fields["cup"], pick_from_selectors("cup"), find_labeled_value(soup, label_map["cup"]))
    fields["face_public"] = first_non_empty(
        fields["face_public"], pick_from_selectors("face_public"), find_labeled_value(soup, label_map["face_public"])
    )

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

    return {
        "name": text_content(name_el),
        "samune": thumb,
        "url": detail_url,
        "oneword": text_content(comment_el),
    }


def scrape_angel():
    env_base_url = os.environ.get("ANGEL_LIVE_BASE_URL", "https://www.angel-live.com/home/")
    base_url = env_base_url.strip() or "https://www.angel-live.com/home/"

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
        if not detail_url or detail_url in seen:
            continue
        seen.add(detail_url)

        detail_fields = {}
        try:
            detail_fields = parse_detail_page(detail_url)
        except Exception as exc:  # noqa: BLE001
            print(f"Detail fetch failed for {detail_url}: {exc}")

        item = {
            "name": info["name"],
            "samune": info["samune"],
            "url": detail_url,
            "oneword": info["oneword"],
            "age": detail_fields.get("age", ""),
            "height": detail_fields.get("height", ""),
            "cup": detail_fields.get("cup", ""),
            "face_public": detail_fields.get("face_public", ""),
            "toy": detail_fields.get("toy", ""),
            "time_slot": detail_fields.get("time_slot", ""),
            "style": detail_fields.get("style", ""),
            "job": detail_fields.get("job", ""),
            "hobby": detail_fields.get("hobby", ""),
            "favorite_type": detail_fields.get("favorite_type", ""),
            "erogenous_zone": detail_fields.get("erogenous_zone", ""),
            "genre": first_non_empty(detail_fields.get("genre_detail", ""), "Angel Live"),
        }

        items.append(item)

    headers = {"X-API-KEY": API_KEY}
    success_count = 0

    for item in items:
        if not item.get("name") or not item.get("url"):
            print("Skipping incomplete item:", item)
            continue

        try:
            r = requests.post(API_URL, json=item, headers=headers, timeout=20)
            r.raise_for_status()
            success_count += 1
            print("Posted:", item["name"], r.text)
        except RequestException as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", "no-status")
            body = getattr(getattr(exc, "response", None), "text", "")
            print(f"Post failed for {item.get('name', '')} (status={status}): {exc}. Body: {body}")

    print("完了：Angel Live 送信数 →", success_count)


if __name__ == "__main__":
    scrape_angel()
