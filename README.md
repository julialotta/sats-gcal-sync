# Sats → Google Calendar Sync

Automatically syncs your booked Sats workout classes to Google Calendar.

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/YOUR_USERNAME/sats-gcal-sync.git
cd sats-gcal-sync
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Create a secret key

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
# Paste the output into .env as SECRET_KEY
```

### 3. Get Google OAuth credentials (one-time)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a new project
2. Enable the **Google Calendar API** (APIs & Services → Library)
3. Go to APIs & Services → Credentials → **Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Web application**
   - Authorized redirect URIs: `http://localhost:5001/oauth/callback`
4. Copy the **Client ID** and **Client Secret** — you'll paste them into the app

### 4. Run the app

```bash
python app.py
```

Open **http://localhost:5001** in your browser.

### 5. Connect everything (first run)

1. **Google Calendar**: paste your Client ID and Client Secret into the form → click **Save & Continue** → authorize in the Google popup
2. **Settings**: enter your Sats email and password → Save
3. **Sync Now** to run the first sync

The app will then automatically sync every hour in the background.

## Files committed to git

| File | Purpose |
|------|---------|
| `app.py` | Flask web app |
| `scraper.py` | Playwright-based Sats scraper |
| `gcal.py` | Google Calendar API wrapper |
| `config.py` | Config loading/saving |
| `scheduler.py` | Background sync scheduler |
| `.env.example` | Template for `SECRET_KEY` |
| `credentials.json.example` | Template for Google OAuth credentials |
| `config.json.example` | Template for Sats credentials |

## Files that are gitignored (created locally)

| File | Contains |
|------|---------|
| `.env` | Your `SECRET_KEY` |
| `credentials.json` | Your Google OAuth client ID + secret |
| `token.json` | Your Google access/refresh tokens |
| `config.json` | Your Sats email + password |
| `browser_state.json` | Saved Playwright browser session |

## Notes

- This app is for **personal use only**. Scraping Sats may violate their Terms of Service.
- Your Sats password is stored locally in `config.json` and only ever sent to `min.sats.se`.
- If Sats changes their login flow or page structure, the scraper selectors in `scraper.py` may need updating.
