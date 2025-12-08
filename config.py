"""
Configuration file for Ottawa Recreation Booking Scraper
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Booking System Configuration
BOOKING_BASE_URL = "https://reservation.frontdesksuite.ca/rcfs/cardelrec"
BOOKING_CF_URL = "https://reservation-cf.frontdeskqms.ca/rcfs/cardelrec"

# Activity Button IDs (extensible for other sports)
ACTIVITY_BUTTON_IDS = {
    'badminton-16+': '2eabeb33-a464-4fd2-af23-6e79329b28d6',
    'badminton-family': 'a44fd57e-8b7d-4594-91f5-ff09cd8d4d17',
    'pickleball': 'bb019a53-4c8e-4cb6-a8bb-a1d744c45c1c',
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

