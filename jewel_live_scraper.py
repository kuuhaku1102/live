"""Scraper for the Jewel Live listing page.

This script fetches the listing page for Jewel Live (j-live.tv), extracts
profile cards, and appends any new entries to a Google Sheet. It is designed
for eventual expansion to a database pipeline by keeping the parsed record
structure explicit.
"""

import base64
import json
import os
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin

import gspread
import mysql.connector
import requests
from bs4 import BeautifulSoup
from mysql.connector import Error as MySQLError

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "YOUR_SPREADSHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "jewel_live")
LISTING_URL = os.environ.get("LISTING_URL", "https://www.j-live.tv/")


def get_gspread_client() -> gspread.Client:
    """Create an authenticated gspread client using base64 JSON credentials."""

    encoded = os.environ.get("GSHEET_JSON")
    if not encoded:
        raise ValueError("GSHEET_JSON not set")

    credentials = json.loads(base64.b64decode(encoded).decode("utf-8"))
    return gspread.service_account_from_dict(credentials)


def open_sheet() -> gspread.Worksheet:
    """Open the configured worksheet within the target spreadsheet."""

    client = get_gspread_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(SHEET_NAME)


def get_db_connection() -> Optional[mysql.connector.MySQLConnection]:
    """Create a MySQL connection if DB settings are provided."""

    host = os.environ.get("DB_HOST")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    database = os.environ.get("DB_NAME")
    port = int(os.environ.get("DB_PORT", "3306"))

    if not host:
        print("DB_HOST not set; skipping database write.")
        return None

    missing = [
        name
        for name, value in {
            "DB_USER": user,
            "DB_PASSWORD": password,
            "DB_NAME": database,
        }.items()
        if not value
    ]

    if missing:
        raise ValueError(f"Missing required database settings: {', '.join(missing)}")

    try:
        connection = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port,
            charset="utf8mb4",
            autocommit=False,
        )
    except MySQLError as exc:
        raise RuntimeError(f"Failed to connect to MySQL: {exc}") from exc

    print(f"Connected to MySQL at {host}:{port}/{database}")
    return connection


def ensure_table(cursor) -> None:
    """Ensure the Jewel Live table exists with a unique URL column."""

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS jewel_live_profiles (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) DEFAULT '',
            image TEXT,
            url VARCHAR(512) NOT NULL UNIQUE,
            comment TEXT,
            viewers VARCHAR(50) DEFAULT '',
            event VARCHAR(255) DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )


def write_profiles_to_db(
    connection: Optional[mysql.connector.MySQLConnection],
    profiles: List[Dict[str, str]],
) -> None:
    """Insert or update profile rows in MySQL when a connection is provided."""

    if not connection:
        return

    cursor = connection.cursor()
    ensure_table(cursor)

    insert_sql = (
        """
        INSERT INTO jewel_live_profiles (name, image, url, comment, viewers, event)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            image = VALUES(image),
            comment = VALUES(comment),
            viewers = VALUES(viewers),
            event = VALUES(event);
        """
    )

    data = [
        (
            item["name"],
            item["image"],
            item["url"],
            item["comment"],
            item["viewers"],
            item["event"],
        )
        for item in profiles
    ]

    cursor.executemany(insert_sql, data)
    connection.commit()
    print(f"Upserted {cursor.rowcount} rows into jewel_live_profiles.")
    cursor.close()


def fetch_html(url: str) -> str:
    """Fetch HTML with a desktop-like User-Agent and a short timeout."""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    return response.text


def extract_background_image(style: str, base_url: str) -> str:
    """Extract a background-image URL from an inline style and absolutize it."""

    match = re.search(r"url\((.*?)\)", style or "")
    if not match:
        return ""
    image_url = match.group(1).strip("'\"")
    return urljoin(base_url, image_url)


def parse_listing(html: str, base_url: str) -> List[Dict[str, str]]:
    """Parse the Jewel Live listing page into a list of profile dictionaries."""

    soup = BeautifulSoup(html, "html.parser")
    entries: List[Dict[str, str]] = []

    for card in soup.select("li.online-girl.party"):
        anchor = card.find("a", href=True)
        if not anchor:
            continue

        profile_url = urljoin(base_url, anchor["href"])
        name_tag = anchor.select_one("li.nick_name h3 b")
        name = name_tag.get_text(strip=True) if name_tag else ""

        comment_tag = anchor.select_one("li.taiki_comment")
        comment = comment_tag.get_text(strip=True) if comment_tag else ""

        image_span = anchor.select_one("li.image span[style]")
        image_url = extract_background_image(
            image_span["style"] if image_span else "", base_url
        )

        viewers_tag = anchor.select_one("li.shityo span")
        viewers = viewers_tag.get_text(strip=True) if viewers_tag else ""

        event_tag = anchor.select_one("li.newface_str")
        event_label = event_tag.get_text(strip=True) if event_tag else ""

        entries.append(
            {
                "name": name,
                "image": image_url,
                "url": profile_url,
                "comment": comment,
                "viewers": viewers,
                "event": event_label,
            }
        )

    return entries


def main() -> None:
    worksheet = open_sheet()
    existing_urls = set(worksheet.col_values(3))  # Column C holds URLs
    db_connection = get_db_connection()

    print(f"Fetching listing page: {LISTING_URL}")
    listing_html = fetch_html(LISTING_URL)
    items = parse_listing(listing_html, LISTING_URL)
    print(f"Found {len(items)} items on the listing page.")

    for item in items:
        if item["url"] in existing_urls:
            continue

        row = [
            item["name"],
            item["image"],
            item["url"],
            item["comment"],
            item["viewers"],
            item["event"],
        ]

        worksheet.append_row(
            row,
            value_input_option="USER_ENTERED",
            table_range="A1:F1",
        )

        print(f"Added: {item['name']} - {item['url']}")

    write_profiles_to_db(db_connection, items)

    if db_connection:
        db_connection.close()
        print("Closed database connection.")


if __name__ == "__main__":
    main()
