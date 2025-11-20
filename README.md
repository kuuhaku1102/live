# live

This repository contains a scraper that extracts profile data from a listing page and appends it to a Google Sheet.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Prepare a Google service account and download the JSON credentials file. Encode this file in base64 and set the result as the environment variable `GSHEET_JSON`.
   ```bash
   base64 credentials.json > credentials.b64
   export GSHEET_JSON=$(cat credentials.b64)
   ```
3. Set the spreadsheet ID and sheet name where the data will be appended:
   ```bash
   export SPREADSHEET_ID=your_spreadsheet_id
   export SHEET_NAME=live
   ```
4. Set the URL of the listing page to scrape. The madamlive scraper uses
   `madam` as the default sheet name, so override it if necessary:
   ```bash
   export LISTING_URL=https://example.com/listing
   export SHEET_NAME=madam
   # Set USE_PLAYWRIGHT=0 to disable JavaScript rendering with Playwright
   export USE_PLAYWRIGHT=1
   ```
5. (Optional) To also persist Jewel Live results to MySQL, provide the database
   connection settings. When these are present, the scraper will upsert data
   into a `jewel_live_profiles` table, creating it if needed.
   ```bash
   export DB_HOST=127.0.0.1
   export DB_PORT=3306
   export DB_USER=username
   export DB_PASSWORD=secret
   export DB_NAME=live
   ```

## Running

Run the scraper with Python:

```bash
python update_sheet.py             # generic scraper
python scrape_madamlive.py         # scraper for madamlive.tv
python dmm_scraper.py              # scraper for DMM live chat
python jewel_live_scraper.py       # scraper for Jewel Live (j-live.tv)
```

These scripts read a listing page, fetch each profile's detail page, and append new entries to the configured Google Sheet.

## GitHub Actions

A workflow in `.github/workflows/update_sheet.yml` can run the generic scraper, `.github/workflows/scrape_madamlive.yml` runs the madamlive-specific one, `.github/workflows/dmm_scraper.yml` runs the DMM scraper, and `.github/workflows/jewel_live.yml` runs the Jewel Live scraper. To use them, add the following secrets to your repository settings:

- `GSHEET_JSON` – base64-encoded service account JSON
- `SPREADSHEET_ID` – ID of the spreadsheet
- `SHEET_NAME` – name of the worksheet (e.g. `live`)
- `LISTING_URL` – listing page URL to scrape
- `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` – database settings
- `SSH_HOST`, `SSH_PORT`, `SSH_USER`, `SSH_PRIVATE_KEY` – SSH tunneling settings for database access

Ensure GitHub Actions are enabled for your repository or configure a self-hosted runner.
