"""
Sats scraper — uses Playwright (headless Chromium) to log in and extract
upcoming booked workout classes from min.sats.se/kommande-traning.

CSS selectors may need adjusting after inspecting the live page with DevTools.
Open the page in Chrome, right-click a booking card → Inspect, and update the
SELECTORS dict below to match the actual DOM structure.
"""

import hashlib
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Selectors — update these after inspecting min.sats.se/kommande-traning
# ---------------------------------------------------------------------------
SELECTORS = {
    # Login page (auth.satsgroup.com uses name='username')
    "email_input": "input[name='username'], input[type='email'], input[name='email'], #email",
    "password_input": "input[type='password'], input[name='password'], #password",
    "login_button": "button[type='submit']",

    # Day group: the <h2> date heading + sibling <ul> of bookings
    # e.g. <h2 class="text--size-headline3">21 feb.</h2>
    "day_group": ".upcoming-trainings-list",

    # Within a day group
    "day_date_heading": "h2",                          # "21 feb."
    "booking_card": "li.upcoming-trainings__day",

    # Within a booking card
    "class_time": "time",                              # "15:30"
    "class_title": ".upcoming-trainings__activity-name .text",
    "class_instructor": ".upcoming-trainings__activity-instructor .text",
    "class_location": ".upcoming-trainings__activity-secondary .text",
    # Duration is not present in the DOM — default 60 min is used as fallback
    "class_duration": "",
}

SATS_BASE_URL = "https://min.sats.se"
SATS_LOGIN_URL = f"{SATS_BASE_URL}/logga-in"
SATS_BOOKINGS_URL = f"{SATS_BASE_URL}/kommande-traning"
BROWSER_STATE_FILE = Path(__file__).parent / "browser_state.json"


def make_sats_id(title: str, start_dt: datetime, location: str) -> str:
    """Stable unique ID for a booking (used to detect duplicates in GCal)."""
    raw = f"{title}|{start_dt.isoformat()}|{location}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _save_storage(context: BrowserContext) -> None:
    context.storage_state(path=str(BROWSER_STATE_FILE))
    logger.debug("Browser session saved to %s", BROWSER_STATE_FILE)


def _login(page: Page, email: str, password: str) -> bool:
    """Perform login. Returns True on success."""
    logger.info("Navigating to login page... current url: %s", page.url)

    try:
        page.wait_for_selector(SELECTORS["email_input"], timeout=10_000)
        page.fill(SELECTORS["email_input"], email)
        page.fill(SELECTORS["password_input"], password)
        page.click(SELECTORS["login_button"])
        # Wait for navigation back to min.sats.se (away from auth server)
        page.wait_for_url(
            lambda url: "min.sats.se" in url and "auth." not in url,
            timeout=20_000,
        )
        logger.info("Login successful, url: %s", page.url)
        return True
    except Exception as exc:
        logger.error("Login failed: %s", exc)
        return False


def _parse_bookings(page: Page) -> list[dict]:
    """Extract booking data from the kommande-traning page."""
    logger.info("Fetching bookings from %s", SATS_BOOKINGS_URL)
    page.goto(SATS_BOOKINGS_URL, wait_until="networkidle")

    # Wait for day groups to appear (SPA — data loads after JS runs)
    try:
        page.wait_for_selector(SELECTORS["day_group"], timeout=15_000)
    except Exception:
        logger.warning(
            "No day groups found with selector '%s'. "
            "The page may be empty, or selectors need updating.",
            SELECTORS["day_group"],
        )
        return []

    day_groups = page.query_selector_all(SELECTORS["day_group"])
    logger.info("Found %d day group(s)", len(day_groups))

    bookings = []
    for group in day_groups:
        date_el = group.query_selector(SELECTORS["day_date_heading"])
        raw_date = date_el.inner_text().strip() if date_el else ""

        cards = group.query_selector_all(SELECTORS["booking_card"])
        for card in cards:
            try:
                booking = _extract_card(card, raw_date)
                if booking:
                    bookings.append(booking)
            except Exception as exc:
                logger.warning("Failed to parse a booking card: %s", exc)

    return bookings


def _extract_card(card, raw_date: str) -> Optional[dict]:
    """Extract fields from a single booking card element."""

    def text(selector: str) -> str:
        if not selector:
            return ""
        el = card.query_selector(selector)
        return el.inner_text().strip() if el else ""

    title = text(SELECTORS["class_title"])
    raw_time = text(SELECTORS["class_time"])
    location = text(SELECTORS["class_location"])
    instructor = text(SELECTORS["class_instructor"])
    duration_text = text(SELECTORS["class_duration"])

    if not title:
        return None  # Skip cards without a title

    # Parse datetime — adapt format strings to match the site's actual format
    start_dt = _parse_datetime(raw_date, raw_time)
    end_dt = _parse_end_time(start_dt, duration_text)

    sats_id = make_sats_id(title, start_dt, location)

    description_parts = []
    if instructor:
        description_parts.append(f"Instructor: {instructor}")
    description_parts.append(f"Synced from Sats (ID: {sats_id})")

    return {
        "sats_id": sats_id,
        "title": title,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "location": location,
        "description": "\n".join(description_parts),
        "instructor": instructor,
    }


def _parse_datetime(raw_date: str, raw_time: str) -> datetime:
    """
    Parse a Swedish short date heading + time string into a datetime.

    raw_date examples: "21 feb.", "5 mar.", "1 jan."
    raw_time examples:  "15:30", "09:00"
    """
    # Swedish abbreviated month names → month number
    SV_MONTHS = {
        "jan": 1, "feb": 2, "mar": 3, "mars": 3, "apr": 4,
        "maj": 5, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "okt": 10, "nov": 11, "dec": 12,
    }

    # Strip trailing dot and whitespace: "21 feb." → ["21", "feb"]
    parts = raw_date.rstrip(".").strip().split()
    if len(parts) >= 2:
        try:
            day = int(parts[0])
            month = SV_MONTHS.get(parts[1].lower().rstrip("."), None)
            if month is not None:
                year = datetime.now().year
                # If the parsed month is earlier than now, it's next year
                now = datetime.now()
                if month < now.month or (month == now.month and day < now.day):
                    year += 1
                hour, minute = (int(x) for x in raw_time.split(":"))
                return datetime(year, month, day, hour, minute)
        except (ValueError, AttributeError):
            pass

    # Fallback for ISO-style dates (just in case)
    if " - " in raw_time:
        raw_time = raw_time.split(" - ")[0].strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(f"{raw_date} {raw_time}".strip(), fmt)
        except ValueError:
            continue

    logger.warning("Could not parse date/time: date=%r time=%r", raw_date, raw_time)
    return datetime.now().replace(second=0, microsecond=0)


def _parse_end_time(start_dt: datetime, duration_text: str) -> datetime:
    """Derive end time from duration string like '45 min' or '1 tim'."""
    minutes = 60  # default fallback

    match = re.search(r"(\d+)\s*min", duration_text, re.IGNORECASE)
    if match:
        minutes = int(match.group(1))
    else:
        match = re.search(r"(\d+)\s*tim", duration_text, re.IGNORECASE)
        if match:
            minutes = int(match.group(1)) * 60

    return start_dt + timedelta(minutes=minutes)


def scrape_bookings(email: str, password: str) -> list[dict]:
    """
    Main entry point. Returns a list of booking dicts.
    Reuses a saved browser session (cookies) when available.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            bookings = _scrape_with_browser(browser, email, password)
        except Exception:
            browser.close()
            raise
        browser.close()

    return bookings


def _scrape_with_browser(browser, email: str, password: str) -> list[dict]:
    """Run the scrape using an already-launched browser instance."""
    # Reuse saved session if it exists and is valid JSON
    context_kwargs = {}
    if BROWSER_STATE_FILE.exists():
        try:
            import json
            json.loads(BROWSER_STATE_FILE.read_text())
            logger.debug("Loading saved browser session from %s", BROWSER_STATE_FILE)
            context_kwargs["storage_state"] = str(BROWSER_STATE_FILE)
        except (json.JSONDecodeError, OSError):
            logger.warning("Browser state file is corrupt — deleting and logging in fresh")
            BROWSER_STATE_FILE.unlink(missing_ok=True)

    context = browser.new_context(**context_kwargs)
    page = context.new_page()

    # Check if we're already logged in by visiting the bookings page
    page.goto(SATS_BOOKINGS_URL, wait_until="networkidle")
    if "/logga-in" in page.url or "/login" in page.url or "auth." in page.url or "openid-connect" in page.url:
        logger.info("Session expired or not found — logging in...")
        if not _login(page, email, password):
            raise RuntimeError(
                "Sats login failed. Check your email/password in the settings."
            )
        _save_storage(context)
        # Navigate back to bookings after login
        page.goto(SATS_BOOKINGS_URL, wait_until="networkidle")

    bookings = _parse_bookings(page)
    _save_storage(context)
    return bookings
