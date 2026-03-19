"""
Configuration file for Ottawa Recreation Booking Scraper
"""

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Recreation Centers in Western Ottawa (Kanata / Stittsville)
# Slug is the identifier used in the FrontDesk Suite booking URL:
#   https://reservation.frontdesksuite.ca/rcfs/<slug>
RECREATION_CENTERS = {
    "richcraftkanata": {
        "name": "Richcraft Recreation Complex – Kanata",
        "slug": "richcraftkanata",
        "area": "Kanata North",
        "page_id": "b3b9b36f-8401-466d-b4c4-19eb5547b43a",
        "activities": {
            "badminton-doubles-adult": {
                "display_name": "Badminton (Doubles – Adult)",
                "button_id": "fac10819-dca0-469c-b6cd-66ce4cdbf810",
                "match_patterns": [
                    r"badminton.*doubles.*adult",
                    r"badminton.*adult(?!.*all)",
                ],
                "group_size_required": True,
            },
            "badminton-doubles-all-ages": {
                "display_name": "Badminton (Doubles – All Ages)",
                "button_id": "2bc7928d-ec91-44e6-a4b0-e8f192ecf5bb",
                "match_patterns": [r"badminton.*all.ages", r"badminton.*doubles.*all"],
                "group_size_required": True,
            },
            "badminton-family": {
                "display_name": "Badminton (Family)",
                "button_id": "fe3f93c8-a615-47ea-82a8-ae8155366e66",
                "match_patterns": [r"badminton.*family"],
                "group_size_required": False,
            },
            # More specific pattern first so "intermediate" text doesn't match rotation
            "pickleball-intermediate": {
                "display_name": "Pickleball (Adult – Intermediate)",
                "button_id": "07497dc5-2307-4832-91f4-d5f67d1803a9",
                "match_patterns": [r"pickleball.*intermediate"],
                "group_size_required": True,
            },
            "pickleball-rotation": {
                "display_name": "Pickleball (Adult – Rotations)",
                "button_id": "07497dc5-2307-4832-91f4-d5f67d1803a9",
                "match_patterns": [r"pickleball.*rotations"],
                "group_size_required": True,
            },
        },
    },
    "cardelrec": {
        "name": "CARDELREC Recreation Complex – Goulbourn",
        "slug": "cardelrec",
        "area": "Stittsville",
        "page_id": "a10d1358-60a7-46b6-b5e9-5b990594b108",
        "activities": {
            "badminton-16plus": {
                "display_name": "Badminton (16+)",
                "button_id": "052c6dfe-5a5c-4e7e-a4ad-f25ce0a4cdb1",
                "match_patterns": [r"badminton.*16\+", r"badminton.*adult(?!.*family)"],
                "group_size_required": True,
            },
            "badminton-family": {
                "display_name": "Badminton (Family)",
                "button_id": "a0145b70-b6a7-4bdf-be65-da5ddb59d99c",
                "match_patterns": [r"badminton.*family"],
                "group_size_required": False,
            },
            "pickleball-adult": {
                "display_name": "Pickleball (Adult)",
                "button_id": "cbc47b51-c574-4ed8-81ee-f414f5072bae",
                "match_patterns": [r"pickleball"],
                "group_size_required": True,
            },
        },
    },
}

# Active center — set ACTIVE_CENTER in your .env to switch facilities
# e.g. ACTIVE_CENTER=walterbaker
ACTIVE_CENTER = os.environ.get("ACTIVE_CENTER", "richcraftkanata")

if ACTIVE_CENTER not in RECREATION_CENTERS:
    raise ValueError(
        f"Unknown ACTIVE_CENTER '{ACTIVE_CENTER}'. "
        f"Valid options: {list(RECREATION_CENTERS.keys())}"
    )

ACTIVE_CENTER_SLUG = RECREATION_CENTERS[ACTIVE_CENTER]["slug"]
_active = RECREATION_CENTERS[ACTIVE_CENTER]

# Booking System Configuration (derived from active center)
BOOKING_BASE_URL = f"https://reservation.frontdesksuite.ca/rcfs/{ACTIVE_CENTER_SLUG}"
BOOKING_CF_URL = f"https://reservation-cf.frontdeskqms.ca/rcfs/{ACTIVE_CENTER_SLUG}"

# Page ID for the active center (used as fallback if not extracted from HTML)
PAGE_ID = _active.get("page_id") or "a10d1358-60a7-46b6-b5e9-5b990594b108"

# Flattened activity dicts derived from the active center — used by scraper as fallbacks
# and by the UI for display. All are keyed by activity_id.
_activities = _active.get("activities", {})

ACTIVITY_BUTTON_IDS: dict = {
    act_id: act["button_id"] for act_id, act in _activities.items()
}
ACTIVITY_DISPLAY_NAMES: dict = {
    act_id: act["display_name"] for act_id, act in _activities.items()
}
ACTIVITY_GROUP_SIZE_REQUIRED: dict = {
    act_id: act["group_size_required"] for act_id, act in _activities.items()
}
# Regex match patterns used by the scraper to identify activity buttons on the page.
# More specific patterns should be listed before generic ones within the same activity.
ACTIVITY_MATCH_PATTERNS: dict = {
    act_id: act["match_patterns"] for act_id, act in _activities.items()
}

# Default settings
DEFAULT_GROUP_SIZE = 2
DEFAULT_CULTURE = "en"
DEFAULT_UI_CULTURE = "en"

# Request settings
REQUEST_DELAY = 1  # Seconds between requests to be respectful
REQUEST_TIMEOUT = 30  # Request timeout in seconds

# Navigation delay settings (for human-like behavior)
NAVIGATION_DELAY_MIN = float(os.environ.get("NAVIGATION_DELAY_MIN", "1.0"))
NAVIGATION_DELAY_MAX = float(os.environ.get("NAVIGATION_DELAY_MAX", "3.0"))

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Flask Configuration
FLASK_SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
FLASK_HOST = os.environ.get("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.environ.get("FLASK_PORT", 5000))

# Contact Info Configuration
CONTACT_NAME = os.environ.get("CONTACT_NAME", "")
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "")
CONTACT_PHONE = os.environ.get("CONTACT_PHONE", "")

# Logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
