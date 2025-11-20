import os
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

API_URL = os.environ.get("API_URL")   # https://s360.jp/index.php?rest_route=/jewel/v1/insert
API_KEY = os.environ.get("API_KEY")   # dLMVcn6fFSP8jzG1SxzAwnmOnCAmC9KqJK6Ykkp2

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
    base_url = "https://www.j-live.tv/"
    html = requests.get(base_url, timeout=15).text
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

        item = {
            "name": name_el.get_text(strip=True) if name_el else "",
            "samune": extract_background_image(
                image_span["style"] if image_span else "", base_url
            ),
            "url": urljoin(base_url, a["href"]),
            "oneword": comment_el.get_text(strip=True) if comment_el else "",
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
            "genre": "Jewel Live",
        }

        items.append(item)

    # WordPress API に送信
    for item in items:
        post_to_wp(item)

    print("完了：Jewel Live 送信数 →", len(items))


if __name__ == "__main__":
    scrape_jewel()
