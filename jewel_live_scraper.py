import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

API_URL = os.environ.get("API_URL")   # https://s360.jp/index.php?rest_route=/jewel/v1/insert
API_KEY = os.environ.get("API_KEY")   # dLMVcn6fFSP8jzG1SxzAwnmOnCAmC9KqJK6Ykkp2

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def make_session() -> requests.Session:
    """Create a session that optionally ignores proxy env vars.

    GitHub-hosted runners sometimes inject proxy settings that block access to
    j-live.tv (e.g., 403 tunnel errors). Set J_LIVE_TRUST_ENV_PROXIES=1 when
    you *do* want to inherit HTTP(S)_PROXY. Otherwise proxies are ignored.
    """

    session = requests.Session()
    trust_env = os.environ.get("J_LIVE_TRUST_ENV_PROXIES", "0") not in {"0", "false", "False", ""}
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
    """Parse detail page-only fields from Jewel Live profiles."""

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
        "toy": ["おもちゃ"],
        "time_slot": ["出没時間", "時間"],
        "style": ["スタイル"],
        "job": ["職業"],
        "hobby": ["趣味"],
        "favorite_type": ["好みのタイプ", "好きなタイプ"],
        "erogenous_zone": ["性感帯"],
    }

    profile_box = soup.select_one("div.profile-box")
    if profile_box:
        for dl in profile_box.select("dl.profile-dl"):
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

        genre_dd = profile_box.select_one("dd.genre-list")
        if genre_dd:
            active_genres = [text_content(div) for div in genre_dd.select("div.genre-div.active")]
            if not active_genres:
                active_genres = [text_content(div) for div in genre_dd.select("div.genre-div")]
            fields["genre_detail"] = ", ".join(filter(None, active_genres))

    selectors = {
        "age": ["dd.p-age", "span.age", "li.age", "td.age"],
        "height": ["dd.p-height", "span.height", "li.height", "td.height"],
        "cup": ["dd.p-cup", "span.cup", "li.cup", "td.cup"],
        "face_public": ["dd.p-face", "span.face", "li.face", "td.face"],
    }

    def pick_from_selectors(keys):
        for sel in selectors[keys]:
            tag = soup.select_one(sel)
            if tag and text_content(tag):
                return text_content(tag)
        return ""

    fields["age"] = first_non_empty(
        fields["age"],
        pick_from_selectors("age"),
        find_labeled_value(soup, ["年齢", "歳", "才"]),
    )
    fields["height"] = first_non_empty(
        fields["height"],
        pick_from_selectors("height"),
        find_labeled_value(soup, ["身長", "cm"]),
    )
    fields["cup"] = first_non_empty(
        fields["cup"],
        pick_from_selectors("cup"),
        find_labeled_value(soup, ["カップ", "バスト"]),
    )
    fields["face_public"] = first_non_empty(
        fields["face_public"],
        pick_from_selectors("face_public"),
        find_labeled_value(soup, ["顔出し", "顔", "公開"]),
    )

    return fields


def post_to_wp(item: dict):
    headers = {"X-API-KEY": API_KEY}
    r = requests.post(API_URL, json=item, headers=headers, timeout=20)
    r.raise_for_status()
    print("Posted:", item["name"], r.text)


def extract_background_image(style: str, base_url: str) -> str:
    m = re.search(r"url\((.*?)\)", style or "")
    if not m:
        return ""
    return urljoin(base_url, m.group(1).strip("'\""))


def scrape_jewel():
    base_url = os.environ.get("J_LIVE_BASE_URL", "https://www.j-live.tv/")
    html = fetch_html(base_url)
    soup = BeautifulSoup(html, "html.parser")

    items = []

    for card in soup.select("li.online-girl.party"):
        a = card.find("a", href=True)
        if not a:
            continue

        name_el = a.select_one("li.nick_name h3 b")
        comment_el = a.select_one("li.taiki_comment")
        image_span = a.select_one("li.image span[style]")
        viewers_el = a.select_one("li.shityo span")
        event_el = a.select_one("li.newface_str")

        detail_url = urljoin(base_url, a["href"])
        detail_fields = {}

        try:
            detail_fields = parse_detail_page(detail_url)
        except Exception as exc:  # noqa: BLE001
            print(f"Detail fetch failed for {detail_url}: {exc}")

        item = {
            "name": name_el.get_text(strip=True) if name_el else "",
            "samune": extract_background_image(
                image_span["style"] if image_span else "", base_url
            ),
            "url": detail_url,
            "oneword": comment_el.get_text(strip=True) if comment_el else "",
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
            "genre": first_non_empty(detail_fields.get("genre_detail", ""), "Jewel Live"),
        }

        items.append(item)

    # WordPress API に送信
    for item in items:
        post_to_wp(item)

    print("完了：Jewel Live 送信数 →", len(items))


if __name__ == "__main__":
    scrape_jewel()

