"""Scraper for the Jewel Live listing page (ConoHa internal execution version).

Runs inside the ConoHa web server via SSH.
Directly connects to internal MySQL (mysql1023.conoha.ne.jp or 172.22.44.179),
no SSH tunnel or external DB access needed.
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


# ----------------------------------------------------------------------
# Google Sheets settings (these still come from GitHub Actions secrets)
# ----------------------------------------------------------------------
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
SHEET_NAME = os.environ.get("SHEET_NAME", "jewel_live")
LISTING_URL = os.environ.get("LISTING_URL", "https://www.j-live.tv/")


# ----------------------------------------------------------------------
# Google Sheets setup
# ----------------------------------------------------------------------
def get_gspread_client() -> gspread.Client:
    encoded = os.environ.get("GSHEET_JSON")
    if not encoded:
        raise ValueError("GSHEET_JSON not set")

    credentials = json.loads(base64.b64decode(encoded).decode("utf-8"))
    return gspread.service_account_from_dict(credentials)


def open_sheet() -> gspread.Worksheet:
    client = get_gspread_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(SHEET_NAME)


# ----------------------------------------------------------------------
# ConoHa Internal MySQL Connection
# ----------------------------------------------------------------------
def get_db_connection() -> Optional[mysql.connector.MySQLConnection]:
    """MySQL for ConoHa internal network (no external access)."""

    host = "mysql1023.conoha.ne.jp"  # internal ConoHa DB host
    # host = "172.22.44.179"          # internal IP (optional)
    user = "jqabp_435b583x"
    password = "admin1116@"
    database = "jqabp_8btdu8jt"
    port = 3306

    try:
        conn = mysql.connector.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port,
            charset="utf8mb4",
            autocommit=False,
        )
    except MySQLError as exc:
        raise RuntimeError(f"FAILED to connect to MySQL internal network: {exc}")

    print(f"[OK] Connected to internal MySQL → {host}:{port}")
    return conn


# ----------------------------------------------------------------------
# Database table creation and upsert
# ----------------------------------------------------------------------
def ensure_table(cursor) -> None:
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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP 
                ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
    )


def write_profiles_to_db(connection, profiles: List[Dict[str, str]]) -> None:
    if not connection:
        return

    cursor = connection.cursor()
    ensure_table(cursor)

    sql = """
        INSERT INTO jewel_live_profiles (name, image, url, comment, viewers, event)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            image = VALUES(image),
            comment = VALUES(comment),
            viewers = VALUES(viewers),
            event = VALUES(event);
    """

    values = [
        (p["name"], p["image"], p["url"], p["comment"], p["viewers"], p["event"])
        for p in profiles
    ]

    cursor.executemany(sql, values)
    connection.commit()

    print(f"[DB] Upserted {cursor.rowcount} rows.")
    cursor.close()


# ----------------------------------------------------------------------
# Scraping
# ----------------------------------------------------------------------
def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
        )
    }
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text


def extract_background_image(style: str, base_url: str) -> str:
    match = re.search(r"url\((.*?)\)", style or "")
    if not match:
        return ""
    img = match.group(1).strip("'\"")
    return urljoin(base_url, img)


def parse_listing(html: str, base_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    for card in soup.select("li.online-girl.party"):
        a = card.find("a", href=True)
        if not a:
            continue

        profile_url = urljoin(base_url, a["href"])
        name_tag = a.select_one("li.nick_name h3 b")
        comment_tag = a.select_one("li.taiki_comment")
        image_span = a.select_one("li.image span[style]")
        viewers_tag = a.select_one("li.shityo span")
        event_tag = a.select_one("li.newface_str")

        entries.append(
            {
                "name": name_tag.get_text(strip=True) if name_tag else "",
                "image": extract_background_image(
                    image_span["style"] if image_span else "", base_url
                ),
                "url": profile_url,
                "comment": comment_tag.get_text(strip=True) if comment_tag else "",
                "viewers": viewers_tag.get_text(strip=True) if viewers_tag else "",
                "event": event_tag.get_text(strip=True) if event_tag else "",
            }
        )

    return entries


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> None:
    print("[INFO] Opening Google Sheet...")
    sheet = open_sheet()
    existing_urls = set(sheet.col_values(3))  # Column C

    print("[INFO] Connecting internal MySQL...")
    conn = get_db_connection()

    print(f"[INFO] Fetching: {LISTING_URL}")
    html = fetch_html(LISTING_URL)
    profiles = parse_listing(html, LISTING_URL)
    print(f"[INFO] Parsed {len(profiles)} profiles.")

    # Insert into Google Sheets
    for p in profiles:
        if p["url"] not in existing_urls:
            row = [
                p["name"],
                p["image"],
                p["url"],
                p["comment"],
                p["viewers"],
                p["event"],
            ]
            sheet.append_row(
                row,
                value_input_option="USER_ENTERED",
                table_range="A1:F1",
            )
            print(f"[SHEET] Added → {p['name']}")

    # Insert into database
    write_profiles_to_db(conn, profiles)

    if conn:
        conn.close()
        print("[OK] MySQL closed.")


if __name__ == "__main__":
    main()
