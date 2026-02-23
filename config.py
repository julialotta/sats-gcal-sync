"""
Loads and saves app configuration from config.json.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULTS = {
    "sats_email": "",
    "sats_password": "",
    "google_calendar_id": "primary",
    "sync_interval_minutes": 60,
}


def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return {**DEFAULTS, **data}
        except json.JSONDecodeError:
            logger.warning("config.json is malformed — using defaults")
    return dict(DEFAULTS)


def save(data: dict) -> None:
    merged = {**load(), **data}
    CONFIG_FILE.write_text(json.dumps(merged, indent=2))
    logger.info("Configuration saved to %s", CONFIG_FILE)


def is_sats_configured() -> bool:
    cfg = load()
    return bool(cfg.get("sats_email") and cfg.get("sats_password"))
