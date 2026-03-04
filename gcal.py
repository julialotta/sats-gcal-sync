"""
Google Calendar API wrapper.

First-time setup:
  1. Go to Google Cloud Console → create a project
  2. Enable the Google Calendar API
  3. Create OAuth 2.0 credentials (Web application)
     - Authorized redirect URI: http://localhost:5000/oauth/callback
  4. Download the credentials JSON and save it as credentials.json in this directory

Tokens are stored in token.json after the first authorization.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"
TOKEN_FILE = Path(__file__).parent / "token.json"

# Extended property key used to tag events created by this app
SATS_ID_PROPERTY = "sats_id"
SATS_APP_PROPERTY = "sats_gcal_sync"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def get_auth_url(redirect_uri: str) -> tuple[str, str]:
    """
    Build the Google OAuth authorization URL for the web flow.
    Returns (auth_url, state).
    """
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.code_verifier = None  # not using PKCE for simplicity
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force refresh token on every authorization
    )
    return auth_url, state


def exchange_code_for_token(code: str, redirect_uri: str) -> None:
    """Exchange the OAuth authorization code for credentials and save to token.json."""
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    flow.fetch_token(code=code)
    creds = flow.credentials
    TOKEN_FILE.write_text(creds.to_json())
    logger.info("Google OAuth token saved to %s", TOKEN_FILE)


def get_service():
    """Load credentials (refreshing if needed) and return a Calendar API service."""
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            "Google Calendar not connected. "
            "Visit /setup in the web app to authorize."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds.expired and creds.refresh_token:
        logger.debug("Refreshing expired Google token...")
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
        except Exception as exc:
            if "invalid_grant" in str(exc).lower():
                logger.warning("Google token revoked or expired — deleting token.json")
                TOKEN_FILE.unlink(missing_ok=True)
                raise TokenRevokedError(
                    "Google authorization has expired or been revoked. "
                    "Please re-authorize."
                ) from exc
            raise

    return build("calendar", "v3", credentials=creds)


class TokenRevokedError(RuntimeError):
    """Raised when the Google OAuth token is revoked or permanently expired."""


def is_connected() -> bool:
    """Return True if a valid token file exists."""
    return TOKEN_FILE.exists()


# ---------------------------------------------------------------------------
# Event management
# ---------------------------------------------------------------------------

def _booking_to_event(booking: dict) -> dict:
    """Convert a booking dict from the scraper to a Google Calendar event body."""
    start_dt: datetime = booking["start_dt"]
    end_dt: datetime = booking["end_dt"]

    # Use local time without timezone if naive; add 'Z' for UTC if needed
    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S")

    return {
        "summary": f"[Sats] {booking['title']}",
        "location": booking.get("location", ""),
        "description": booking.get("description", ""),
        "start": {"dateTime": fmt(start_dt), "timeZone": "Europe/Stockholm"},
        "end": {"dateTime": fmt(end_dt), "timeZone": "Europe/Stockholm"},
        "extendedProperties": {
            "private": {
                SATS_ID_PROPERTY: booking["sats_id"],
                SATS_APP_PROPERTY: "true",
            }
        },
    }


def _get_existing_sats_events(service, calendar_id: str) -> dict[str, str]:
    """
    Return a dict of {sats_id: google_event_id} for all events
    created by this app in the calendar.
    """
    existing = {}
    page_token = None

    while True:
        response = service.events().list(
            calendarId=calendar_id,
            privateExtendedProperty=f"{SATS_APP_PROPERTY}=true",
            maxResults=500,
            pageToken=page_token,
            fields="nextPageToken,items(id,extendedProperties)",
        ).execute()

        for item in response.get("items", []):
            props = item.get("extendedProperties", {}).get("private", {})
            sats_id = props.get(SATS_ID_PROPERTY)
            if sats_id:
                existing[sats_id] = item["id"]

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return existing


def sync_bookings(bookings: list[dict], calendar_id: str = "primary") -> dict:
    """
    Sync a list of bookings to Google Calendar.
    - Creates events that don't exist yet
    - Updates events whose details changed (same sats_id)
    - Deletes events that are no longer in the booking list (cancelled)

    Returns a summary dict: {created, updated, deleted, errors}.
    """
    service = get_service()
    summary = {"created": 0, "updated": 0, "deleted": 0, "errors": 0}

    existing = _get_existing_sats_events(service, calendar_id)
    incoming_ids = {b["sats_id"] for b in bookings}

    # Upsert each incoming booking
    for booking in bookings:
        sats_id = booking["sats_id"]
        event_body = _booking_to_event(booking)
        try:
            if sats_id in existing:
                # Update existing event
                service.events().update(
                    calendarId=calendar_id,
                    eventId=existing[sats_id],
                    body=event_body,
                ).execute()
                summary["updated"] += 1
                logger.debug("Updated event for booking %s (%s)", sats_id, booking["title"])
            else:
                # Create new event
                service.events().insert(
                    calendarId=calendar_id,
                    body=event_body,
                ).execute()
                summary["created"] += 1
                logger.info("Created event: %s on %s", booking["title"], booking["start_dt"])
        except HttpError as exc:
            logger.error("GCal API error for booking %s: %s", sats_id, exc)
            summary["errors"] += 1

    # Delete events that are no longer booked (cancelled classes)
    stale_ids = set(existing.keys()) - incoming_ids
    for sats_id in stale_ids:
        try:
            service.events().delete(
                calendarId=calendar_id,
                eventId=existing[sats_id],
            ).execute()
            summary["deleted"] += 1
            logger.info("Deleted stale event (sats_id=%s)", sats_id)
        except HttpError as exc:
            if exc.resp.status == 410:
                # Already deleted — ignore
                pass
            else:
                logger.error("Failed to delete event %s: %s", sats_id, exc)
                summary["errors"] += 1

    return summary
