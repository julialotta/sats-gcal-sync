"""
Sats → Google Calendar Sync — Flask web app

Run with:
    python app.py

Then open http://localhost:5000 in your browser.
"""

import logging
import os
import secrets
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


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------
def run_sync() -> dict:
    """Run a full Sats → GCal sync cycle. Returns result summary."""
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

        summary = gcal.sync_bookings(bookings, conf["google_calendar_id"])
        result.update(summary)
        result["status"] = "ok"
        result["message"] = (
            f"Synced {len(bookings)} booking(s): "
            f"{summary['created']} created, {summary['updated']} updated, "
            f"{summary['deleted']} deleted."
        )
        logger.info(result["message"])
    except Exception as exc:
        result["message"] = str(exc)
        logger.exception("Sync failed: %s", exc)

    _log(result)
    return result


def _log(result: dict) -> None:
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
        sats_configured=cfg.is_sats_configured(),
        last_sync=last_sync_result,
        sync_log=sync_log[:20],
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
    flash(result["message"], "success" if result["status"] == "ok" else "danger")
    return redirect(url_for("index"))


@app.route("/status")
def status():
    return jsonify(last_sync_result)


# ---------------------------------------------------------------------------
# Google OAuth routes
# ---------------------------------------------------------------------------

@app.route("/setup")
def setup():
    if not gcal.CREDENTIALS_FILE.exists():
        flash(
            "credentials.json not found. Download it from Google Cloud Console "
            "and place it in the project directory.",
            "danger",
        )
        return redirect(url_for("index"))

    redirect_uri = "http://localhost:5001/oauth/callback"
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
        redirect_uri = "http://localhost:5001/oauth/callback"
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
