"""
Configuration file for Ottawa Recreation Booking Scraper
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Booking System Configuration
DEFAULT_CENTER = os.environ.get('BOOKING_CENTER', 'cardelrec')


def build_booking_url(center: str) -> str:
    """Build booking URL for a center."""
    return f"https://reservation.frontdesksuite.ca/rcfs/{center}"


def build_booking_cf_url(center: str) -> str:
    """Build CF booking URL for a center."""
    return f"https://reservation-cf.frontdeskqms.ca/rcfs/{center}"


BOOKING_BASE_URL = build_booking_url(DEFAULT_CENTER)
BOOKING_CF_URL = build_booking_cf_url(DEFAULT_CENTER)

# Activity Button IDs (extensible for other sports)
# Note: As of 2024, racquet sports (Badminton, Pickleball) are now organized 
# under the "Gymnasium sports" category in the Ottawa recreation booking system.
# 
# IMPORTANT: Button IDs are now extracted dynamically from the booking page HTML.
# These values are kept as fallback/validation only and may be outdated.
# The scraper will extract actual button IDs from the page at runtime.
ACTIVITY_BUTTON_IDS = {
    'badminton-16+': '052c6dfe-5a5c-4e7e-a4ad-f25ce0a4cdb1',  # Fallback - may be outdated
    'badminton-family': 'a44fd57e-8b7d-4594-91f5-ff09cd8d4d17',  # Fallback - may be outdated
    'pickleball': 'bb019a53-4c8e-4cb6-a8bb-a1d744c45c1c',  # Fallback - may be outdated
    # Add more activities here as needed
}

# Page ID (may need to be updated if it changes)
PAGE_ID = "a10d1358-60a7-46b6-b5e9-5b990594b108"

# Default settings
DEFAULT_GROUP_SIZE = 2
DEFAULT_CULTURE = "en"
DEFAULT_UI_CULTURE = "en"

# Activity display names for UI
ACTIVITY_DISPLAY_NAMES = {
    'badminton-16+': 'Badminton (16+)',
    'badminton-family': 'Badminton (Family)',
    'pickleball': 'Pickleball',
}

# Group size requirement per activity
ACTIVITY_GROUP_SIZE_REQUIRED = {
    'badminton-16+': True,
    'badminton-family': False, 
    'pickleball': True,
}

# Request settings
REQUEST_DELAY = 1  # Seconds between requests to be respectful
REQUEST_TIMEOUT = 30  # Request timeout in seconds

# Navigation delay settings (for human-like behavior)
NAVIGATION_DELAY_MIN = float(os.environ.get('NAVIGATION_DELAY_MIN', '1.0'))
NAVIGATION_DELAY_MAX = float(os.environ.get('NAVIGATION_DELAY_MAX', '3.0'))

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
TELEGRAM_CHAT_IDS = [chat_id.strip() for chat_id in os.environ.get('TELEGRAM_CHAT_IDS', '').split(',') if chat_id.strip()]

# Flask Configuration
FLASK_SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
FLASK_DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
FLASK_HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
FLASK_PORT = int(os.environ.get('FLASK_PORT', 5000))

# Contact Info Configuration
CONTACT_NAME = os.environ.get('CONTACT_NAME', '')
CONTACT_EMAIL = os.environ.get('CONTACT_EMAIL', '')
CONTACT_PHONE = os.environ.get('CONTACT_PHONE', '')

# Logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

