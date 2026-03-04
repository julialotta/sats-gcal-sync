"""
Sats → Google Calendar Sync — Flask web app

Run with:
    python app.py

Then open http://localhost:5001 in your browser.
"""

import json
import logging
import os
import secrets
import threading
from datetime import datetime

from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
    jsonify,
    flash,
)

import config as cfg
import gcal
import scraper
import scheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

# Sync state (in-memory — resets on restart)
sync_log: list[dict] = []
last_sync_result: dict = {}
last_bookings: list[dict] = []
_sync_lock = threading.Lock()  # prevents concurrent syncs


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------
def run_sync() -> dict:
    """Run a full Sats → GCal sync cycle. Returns result summary."""
    if not _sync_lock.acquire(blocking=False):
        logger.info("Sync already in progress — skipping")
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "status": "error",
            "message": "Sync already in progress.",
            "created": 0, "updated": 0, "deleted": 0, "bookings_found": 0,
        }

    try:
        return _do_sync()
    finally:
        _sync_lock.release()


def _do_sync() -> dict:
    """Inner sync logic — called only when lock is held."""
    conf = cfg.load()
    result = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "status": "error",
        "message": "",
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "bookings_found": 0,
    }

    if not cfg.is_sats_configured():
        result["message"] = "Sats credentials not configured."
        _log(result)
        return result

    if not gcal.is_connected():
        result["message"] = "Google Calendar not connected."
        _log(result)
        return result

    try:
        logger.info("Starting sync...")
        bookings = scraper.scrape_bookings(conf["sats_email"], conf["sats_password"])
        result["bookings_found"] = len(bookings)

        global last_bookings
        last_bookings = bookings

        summary = gcal.sync_bookings(bookings, conf["google_calendar_id"])
        result.update(summary)
        result["status"] = "ok"
        result["message"] = (
            f"Synced {len(bookings)} booking(s): "
            f"{summary['created']} created, {summary['updated']} updated, "
            f"{summary['deleted']} deleted."
        )
        logger.info(result["message"])
    except gcal.TokenRevokedError as exc:
        result["message"] = str(exc)
        result["reauth_required"] = True
        logger.warning("Token revoked — user needs to re-authorize")
    except Exception as exc:
        result["message"] = str(exc)
        logger.exception("Sync failed: %s", exc)

    _log(result)
    return result


def _log(result: dict) -> None:  # noqa: E302
    global last_sync_result
    last_sync_result = result
    sync_log.insert(0, result)
    if len(sync_log) > 50:
        sync_log.pop()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    conf = cfg.load()
    return render_template(
        "index.html",
        config=conf,
        gcal_connected=gcal.is_connected(),
        gcal_credentials_set=gcal.CREDENTIALS_FILE.exists(),
        sats_configured=cfg.is_sats_configured(),
        last_sync=last_sync_result,
        sync_log=sync_log[:20],
        bookings=last_bookings,
        just_synced=request.args.get("synced") == "1",
        reauth_required=request.args.get("reauth") == "1",
    )


@app.route("/settings", methods=["POST"])
def save_settings():
    data = {
        "sats_email": request.form.get("sats_email", "").strip(),
        "sats_password": request.form.get("sats_password", ""),
        "google_calendar_id": request.form.get("google_calendar_id", "primary").strip(),
    }
    cfg.save(data)
    flash("Settings saved.", "success")
    return redirect(url_for("index"))


@app.route("/sync", methods=["POST"])
def sync_now():
    result = run_sync()
    if request.headers.get("Accept") == "application/json":
        return jsonify(result)
    if result.get("reauth_required"):
        flash(result["message"], "danger")
        return redirect(url_for("index", reauth="1"))
    flash(result["message"], "success" if result["status"] == "ok" else "danger")
    return redirect(url_for("index", synced="1"))


@app.route("/status")
def status():
    data = dict(last_sync_result)
    data["bookings"] = [
        {"title": b["title"], "start_dt": b["start_dt"].strftime("%-d %b %H:%M")}
        for b in last_bookings
    ]
    return jsonify(data)


# ---------------------------------------------------------------------------
# Google OAuth routes
# ---------------------------------------------------------------------------

@app.route("/google-credentials", methods=["POST"])
def save_google_credentials():
    """Accept Google OAuth client ID + secret from the setup form and write credentials.json."""
    client_id = request.form.get("client_id", "").strip()
    client_secret = request.form.get("client_secret", "").strip()

    if not client_id or not client_secret:
        flash("Both Client ID and Client Secret are required.", "danger")
        return redirect(url_for("index"))

    creds_data = {
        "web": {
            "client_id": client_id,
            "project_id": "sats-gcal-sync",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
            "redirect_uris": [request.host_url.rstrip("/") + "/oauth/callback"],
        }
    }

    gcal.CREDENTIALS_FILE.write_text(json.dumps(creds_data, indent=2))
    flash("Google credentials saved. Now click 'Connect with Google'.", "success")
    return redirect(url_for("index"))


@app.route("/setup")
def setup():
    if not gcal.CREDENTIALS_FILE.exists():
        flash(
            "Enter your Google OAuth Client ID and Secret below first.",
            "danger",
        )
        return redirect(url_for("index"))

    redirect_uri = request.host_url.rstrip("/") + "/oauth/callback"
    auth_url, state = gcal.get_auth_url(redirect_uri)
    session["oauth_state"] = state
    return redirect(auth_url)


@app.route("/oauth/callback")
def oauth_callback():
    code = request.args.get("code")
    if not code:
        flash("Google authorization failed — no code received.", "danger")
        return redirect(url_for("index"))

    try:
        redirect_uri = request.host_url.rstrip("/") + "/oauth/callback"
        gcal.exchange_code_for_token(code, redirect_uri)
        flash("Google Calendar connected successfully!", "success")
    except Exception as exc:
        logger.exception("OAuth callback error")
        flash(f"Google authorization error: {exc}", "danger")

    return redirect(url_for("index"))


@app.route("/disconnect")
def disconnect():
    if gcal.TOKEN_FILE.exists():
        gcal.TOKEN_FILE.unlink()
        flash("Google Calendar disconnected.", "info")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    conf = cfg.load()
    scheduler.start(run_sync, interval_minutes=conf["sync_interval_minutes"])

    # Run on all interfaces so it's reachable on the local network if needed
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
