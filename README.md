# Sats → Google Calendar Sync

Automatically syncs your booked Sats workout classes to Google Calendar. Runs as a local web app with a background scheduler that syncs every hour.

## How it works

1. Logs in to `min.sats.se` using Playwright (headless Chromium)
2. Scrapes your upcoming booked classes from the bookings page
3. Creates/updates/deletes Google Calendar events to match
4. Runs automatically every hour in the background

## Setup

### 1. Clone and install

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
# Edit .env and replace the SECRET_KEY value with the output of:
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Run the app

```bash
python app.py
```

Open **http://localhost:5001** in your browser.

### 4. First-time setup (in the browser)

1. **Google Calendar**: enter your OAuth Client ID and Secret (see below) → Save → Connect with Google → authorize in the popup
2. **Settings**: enter your Sats email and password → Save
3. Click **Sync Now** to run the first sync

The app syncs automatically every hour after that.

### Getting Google OAuth credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a new project
2. Enable the **Google Calendar API** (APIs & Services → Library)
3. Go to APIs & Services → Credentials → **Create Credentials → OAuth 2.0 Client ID**
   - Application type: **Web application**
   - Authorized redirect URI: `http://localhost:5001/oauth/callback`
4. Copy the **Client ID** and **Client Secret** — paste them into the app's setup form

## Files

### Committed to git

| File | Purpose |
|------|---------|
| `app.py` | Flask web app and sync orchestration |
| `scraper.py` | Playwright scraper for min.sats.se |
| `gcal.py` | Google Calendar API wrapper |
| `config.py` | Config file loading/saving |
| `scheduler.py` | Background hourly sync |
| `templates/index.html` | Web UI |
| `.env.example` | Template for `SECRET_KEY` |
| `credentials.json.example` | Template for Google OAuth credentials |
| `config.json.example` | Template for Sats credentials |

### Gitignored (created locally, never committed)

| File | Contains |
|------|---------|
| `.env` | Your `SECRET_KEY` |
| `credentials.json` | Your Google OAuth client ID + secret |
| `token.json` | Your Google access/refresh tokens |
| `config.json` | Your Sats email + password |
| `browser_state.json` | Saved Playwright browser session (auto-managed) |

## Keeping it running

To keep the app running in the background on Mac, create a launchd service:

```bash
# Create ~/Library/LaunchAgents/sats-gcal-sync.plist
# Then: launchctl load ~/Library/LaunchAgents/sats-gcal-sync.plist
```

Or just run it in a terminal session with `python app.py`.

## Troubleshooting

**"0 bookings found"** — The Sats page structure may have changed. Open Chrome, log in to `min.sats.se/kommande-traning`, right-click a booking card → Inspect, and compare the CSS classes against the `SELECTORS` dict in `scraper.py`.

**Login fails** — Check your Sats email/password in Settings. The scraper logs in via `auth.satsgroup.com` (Sats's OAuth provider).

**Google Calendar errors** — Try disconnecting and reconnecting Google Calendar via the UI. If the token is expired or revoked, reconnecting will get a fresh one.

## Notes

- Personal use only. Scraping Sats may violate their Terms of Service.
- Your Sats password is stored locally in `config.json` and only ever sent to `min.sats.se`.
- Syncs are de-duplicated — running sync multiple times won't create duplicate calendar events.
- Cancelled classes (removed from your Sats bookings) are automatically deleted from Google Calendar.
