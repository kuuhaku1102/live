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
4. Set the URL of the listing page to scrape:
   ```bash
   export LISTING_URL=https://example.com/listing
   ```

## Running

Run the scraper with Python:

```bash
python update_sheet.py
```

The script reads the listing page, fetches each profile's detail page, and appends any new entries to the specified Google Sheet.
