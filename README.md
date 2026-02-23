# Sats → Google Calendar Sync

Automatically syncs your booked Sats workout classes to Google Calendar.

## Quick start

### 1. Install dependencies

```bash
cd sats-gcal-sync
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Set up Google Calendar API (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a new project
2. Enable the **Google Calendar API** (APIs & Services → Library)
3. Go to APIs & Services → Credentials → **Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Web application**
   - Authorized redirect URIs: `http://localhost:5000/oauth/callback`
4. Download the JSON file and save it as **`credentials.json`** in this directory

### 3. Run the app

```bash
python app.py
```

Open **http://localhost:5000** in your browser.

### 4. Connect everything

1. Click **Settings** → enter your Sats email and password → Save
2. Click **Connect with Google** → authorize in your browser
3. Click **Sync Now** to run the first sync

The app will then automatically sync every hour in the background.

## Updating scraper selectors

`min.sats.se` is a JavaScript SPA. If the sync finds no bookings, the CSS selectors
in [scraper.py](scraper.py) (the `SELECTORS` dict at the top) may need updating:

1. Log in to https://min.sats.se/kommande-traning in Chrome
2. Right-click a booking card → **Inspect**
3. Find the CSS classes/IDs for: booking card, title, time, date, location, instructor
4. Update the `SELECTORS` dict in `scraper.py` accordingly

## Files

| File | Purpose |
|------|---------|
| `app.py` | Flask web app, routes, sync logic |
| `scraper.py` | Playwright-based Sats scraper |
| `gcal.py` | Google Calendar API wrapper |
| `config.py` | Config loading/saving |
| `scheduler.py` | APScheduler background sync |
| `credentials.json` | Google OAuth credentials (**gitignored**) |
| `token.json` | Google access/refresh tokens (**gitignored**) |
| `config.json` | Sats credentials & settings (**gitignored**) |
| `browser_state.json` | Saved Playwright session (**gitignored**) |

## Notes

- This app is for **personal use only**. Scraping Sats may violate their Terms of Service.
- Your Sats password is stored locally in `config.json` and never sent anywhere except to `min.sats.se`.
- If Sats adds CAPTCHA or changes their login flow, the scraper may stop working.
