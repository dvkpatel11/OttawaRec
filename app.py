from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import json
import logging
import requests
from dotenv import load_dotenv
from scraper import OttawaRecBookingScraper
from telegram_notifier import TelegramNotifier
from config import FLASK_SECRET_KEY, FLASK_HOST, FLASK_PORT
import config as _config
import scraper as _scraper_module
import threading
import time

CHAT_IDS_FILE = os.path.join(os.path.dirname(__file__), 'chat_ids.json')


def load_chat_ids() -> list:
    """Load chat IDs from persistent JSON file, seeding from env if file is new."""
    from config import TELEGRAM_CHAT_ID
    if os.path.exists(CHAT_IDS_FILE):
        try:
            with open(CHAT_IDS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    # Seed from env var on first run
    ids = [TELEGRAM_CHAT_ID] if TELEGRAM_CHAT_ID else []
    save_chat_ids(ids)
    return ids


def save_chat_ids(ids: list) -> None:
    """Persist chat IDs to JSON file."""
    try:
        with open(CHAT_IDS_FILE, 'w') as f:
            json.dump(ids, f)
    except Exception as e:
        logger_bootstrap = logging.getLogger(__name__)
        logger_bootstrap.error(f"Failed to save chat IDs: {e}")

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

# Enable CORS for all routes (needed for WSL/network access)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Add headers to all responses
@app.after_request
def after_request(response):
    """Add headers to all responses"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# Configure logging - show errors and warnings with more detail
logging.basicConfig(
    level=logging.WARNING,  # Show WARNING and ERROR
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress werkzeug INFO logs for successful requests (only log errors)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Initialize components
telegram = TelegramNotifier()
# Load persisted chat IDs and apply to notifier
_stored_ids = load_chat_ids()
if _stored_ids:
    telegram.set_chat_ids(_stored_ids)


def _handle_telegram_message(message: dict):
    """Shared logic for registering a user from an incoming Telegram message."""
    chat = message.get('chat', {})
    chat_id = str(chat.get('id', ''))
    if not chat_id:
        return
    text = (message.get('text') or '').strip().lower()
    first_name = chat.get('first_name') or 'there'

    if text == '/stop':
        if telegram.remove_chat_id(chat_id):
            save_chat_ids(telegram.chat_ids)
            telegram.send_to(chat_id,
                "✅ You've been removed from the Ottawa Rec notification list.\n"
                "Send any message to re-subscribe."
            )
    else:
        if telegram.add_chat_id(chat_id):
            save_chat_ids(telegram.chat_ids)
            from config import RECREATION_CENTERS, ACTIVE_CENTER
            center_name = RECREATION_CENTERS[ACTIVE_CENTER]['name']
            telegram.send_to(chat_id,
                f"👋 Hi {first_name}! You're now subscribed to <b>Ottawa Rec Booking</b> alerts.\n\n"
                f"📍 Currently watching: <b>{center_name}</b>\n\n"
                f"You'll get a message as soon as a slot opens up.\n\n"
                f"Send /stop at any time to unsubscribe."
            )


def _telegram_poll_loop():
    """Long-poll Telegram for incoming messages and auto-register senders.
    Used when a webhook isn't available (local dev, HTTP-only environments).
    """
    offset = 0
    base = f"https://api.telegram.org/bot{telegram.bot_token}"
    while True:
        try:
            resp = requests.get(
                f"{base}/getUpdates",
                params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
                timeout=35,
            )
            if resp.status_code != 200:
                time.sleep(5)
                continue
            data = resp.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message") or update.get("edited_message")
                if msg:
                    _handle_telegram_message(msg)
        except Exception:
            time.sleep(5)


if telegram.enabled:
    _poll_thread = threading.Thread(target=_telegram_poll_loop, daemon=True)
    _poll_thread.start()

# Shared scrapers used for monitoring / check-now (one per activity type).
# Keeping a single HTTP session per activity avoids the booking site's
# "multiple browser tabs" detection, which triggers when multiple requests.Session()
# objects hit the site simultaneously.
monitoring_processes = {}  # {activity_type: {active, group_size, ...}}
shared_scrapers = {}       # {activity_type: OttawaRecBookingScraper}

# Per-browser-session scrapers used ONLY for the booking flow (select-slot,
# submit-contact).  Each user gets their own isolated HTTP session so their
# booking state doesn't collide with other users.
booking_scrapers = {}  # {session_id: {activity_type: OttawaRecBookingScraper}}

def _session_id() -> str:
    """Extract the browser session ID from the request header."""
    return request.headers.get('X-Session-Id', 'default')

def get_shared_scraper(activity_type: str) -> 'OttawaRecBookingScraper':
    """Get or create the shared (monitoring) scraper for an activity type."""
    if activity_type not in shared_scrapers:
        s = OttawaRecBookingScraper()
        s.clear_screenshots()
        shared_scrapers[activity_type] = s
    return shared_scrapers[activity_type]

def get_booking_scraper(session_id: str, activity_type: str) -> 'OttawaRecBookingScraper':
    """Get or create a per-session scraper for the booking flow."""
    if session_id not in booking_scrapers:
        booking_scrapers[session_id] = {}
    if activity_type not in booking_scrapers[session_id]:
        s = OttawaRecBookingScraper()
        s.clear_screenshots()
        booking_scrapers[session_id][activity_type] = s
    return booking_scrapers[session_id][activity_type]

# Session lock to prevent multiple simultaneous bookings
import threading
session_lock = threading.Lock()


def monitor_loop(activity_type: str = 'badminton-16+', group_size: int = 2):
    """Background monitoring loop using the shared scraper for an activity type."""
    global monitoring_processes

    scraper = get_shared_scraper(activity_type)

    if not scraper.initialize_session():
        logger.error(f"Failed to initialize scraper for {activity_type}")
        telegram.notify_error(f"Failed to initialize booking session for {activity_type}")
        if activity_type in monitoring_processes:
            monitoring_processes[activity_type]['active'] = False
        return

    check_count = 0
    while monitoring_processes.get(activity_type, {}).get('active', False):
        try:
            check_count += 1
            proc = monitoring_processes[activity_type]

            with session_lock:
                if not scraper.current_session_id:
                    if not scraper.initialize_session():
                        logger.error(f"Failed to re-initialize scraper for {activity_type}")
                        telegram.notify_error(f"Failed to re-initialize session for {activity_type}")
                        proc['last_error'] = {'message': 'Failed to re-initialize session', 'error_type': 'session_error'}
                        time.sleep(60)
                        continue

                result = scraper.get_available_slots(activity_type, group_size, navigate=True)
                slots = result.get('slots', []) if result.get('success') else []

                if result.get('screenshot'):
                    proc['screenshot'] = result['screenshot']
                elif hasattr(scraper, 'screenshots') and activity_type in scraper.screenshots:
                    proc['screenshot'] = scraper.screenshots[activity_type]

                if not result.get('success'):
                    proc['last_error'] = {
                        'message': result.get('message', 'Unknown error'),
                        'error_type': result.get('error_type', 'unknown_error'),
                        'status_code': result.get('status_code'),
                    }
                    if result.get('error_type') in ['session_error', 'authentication_error']:
                        scraper.current_session_id = None
                    if result.get('screenshot'):
                        proc['screenshot'] = result['screenshot']
                    elif hasattr(scraper, 'screenshots') and activity_type in scraper.screenshots:
                        proc['screenshot'] = scraper.screenshots[activity_type]

            previous_slot_count = len(proc.get('slots') or [])
            proc['slots'] = slots

            if slots:
                should_notify = (check_count == 1 or previous_slot_count == 0 or len(slots) > previous_slot_count)
                if should_notify:
                    telegram.notify_slot_found(slots, activity_type)

            wait_seconds = 300
            if monitoring_processes.get(activity_type, {}).get('active', False):
                for _ in range(wait_seconds):
                    if not monitoring_processes.get(activity_type, {}).get('active', False):
                        break
                    time.sleep(1)

        except Exception as e:
            import traceback
            logger.error(f"Monitoring error for {activity_type}: {str(e)}\n{traceback.format_exc()}")
            telegram.notify_error(f"Monitoring error for {activity_type}: {str(e)}")
            time.sleep(60)

    if activity_type in monitoring_processes:
        monitoring_processes[activity_type]['active'] = False


@app.route('/', methods=['GET', 'OPTIONS'])
def index():
    """Main page with table view"""
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        response = jsonify({})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', '*')
        response.headers.add('Access-Control-Allow-Methods', '*')
        return response, 200
    
    return render_template('index.html')




@app.route('/api/start', methods=['POST'])
def start_monitoring():
    """Start the monitoring and booking process for a specific activity"""
    global monitoring_processes

    try:
        data = request.json or {}
        activity_type = data.get('activity_type', 'badminton-16+')
        group_size = int(data.get('group_size', 2))
        # Validate group size
        if group_size < 1 or group_size > 10:
            return jsonify({
                'success': False,
                'message': 'Group size must be between 1 and 10'
            }), 400

        # Check if already monitoring this activity
        if monitoring_processes.get(activity_type, {}).get('active', False):
            return jsonify({
                'success': False,
                'message': 'Monitoring is already active for this sport'
            }), 400

        # Create new monitoring process (shared across all sessions)
        monitoring_processes[activity_type] = {
            'active': True,
            'group_size': group_size,
            'result': None
        }

        thread = threading.Thread(
            target=monitor_loop,
            args=(activity_type, group_size),
            daemon=True
        )
        thread.start()
        monitoring_processes[activity_type]['thread'] = thread

        return jsonify({
            'success': True,
            'message': 'Monitoring started successfully'
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Failed to start monitoring: {str(e)}\n{error_details}")
        activity_type = (request.json or {}).get('activity_type', 'badminton-16+')
        if activity_type in monitoring_processes:
            monitoring_processes[activity_type]['active'] = False
        return jsonify({
            'success': False,
            'message': f'Failed to start: {str(e)}'
        }), 500


@app.route('/api/stop', methods=['POST'])
def stop_monitoring():
    """Stop the monitoring process for a specific activity"""
    global monitoring_processes

    try:
        data = request.json or {}
        activity_type = data.get('activity_type')

        if not activity_type:
            return jsonify({
                'success': False,
                'message': 'Activity type is required'
            }), 400

        if not monitoring_processes.get(activity_type, {}).get('active', False):
            return jsonify({
                'success': False,
                'message': 'Monitoring is not active for this sport'
            }), 400

        monitoring_processes[activity_type]['active'] = False

        return jsonify({
            'success': True,
            'message': 'Monitoring stopped'
        })
    except Exception as e:
        logger.error(f"Failed to stop monitoring: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Failed to stop: {str(e)}'
        }), 500


@app.route('/api/status', methods=['GET'])
def status():
    """Get current status for all processes for this session"""
    global monitoring_processes

    processes = {}
    last_check_times = {}

    for activity_type, process in monitoring_processes.items():
        screenshot_path = None
        scraper = shared_scrapers.get(activity_type)
        if scraper:
            if hasattr(scraper, 'screenshots') and activity_type in scraper.screenshots:
                screenshot_path = scraper.screenshots[activity_type]
            if scraper.last_check_time:
                last_check_times[activity_type] = scraper.last_check_time.isoformat()
        elif 'screenshot' in process:
            screenshot_path = process.get('screenshot')

        processes[activity_type] = {
            'active': process.get('active', False),
            'group_size': process.get('group_size', 2),
            'result': process.get('result'),
            'screenshot': screenshot_path,
            'slots': process.get('slots', []),
            'last_error': process.get('last_error')
        }

    return jsonify({
        'processes': processes,
        'last_check': last_check_times,
        'telegram_enabled': telegram.enabled,
        'booking_url': _config.BOOKING_BASE_URL,
        'active_center': _config.ACTIVE_CENTER,
    })




@app.route('/api/centers', methods=['GET'])
def get_centers():
    """Return all available centers and the currently active one"""
    return jsonify({
        'centers': _config.RECREATION_CENTERS,
        'active_center': _config.ACTIVE_CENTER,
        'booking_url': _config.BOOKING_BASE_URL,
    })


@app.route('/api/set-center', methods=['POST'])
def set_center():
    """Switch the active recreation center at runtime"""
    data = request.json or {}
    center_id = data.get('center_id')

    if center_id not in _config.RECREATION_CENTERS:
        return jsonify({'success': False, 'message': f'Unknown center: {center_id}'}), 400

    # Stop all active monitoring and clear all scraper instances
    for proc in monitoring_processes.values():
        proc['active'] = False
    monitoring_processes.clear()
    shared_scrapers.clear()
    booking_scrapers.clear()

    # Update config globals
    center = _config.RECREATION_CENTERS[center_id]
    slug = center['slug']
    activities = center.get('activities', {})

    _config.ACTIVE_CENTER = center_id
    _config.ACTIVE_CENTER_SLUG = slug
    _config.BOOKING_BASE_URL = f"https://reservation.frontdesksuite.ca/rcfs/{slug}"
    _config.BOOKING_CF_URL = f"https://reservation-cf.frontdeskqms.ca/rcfs/{slug}"
    _config.PAGE_ID = center.get('page_id') or _config.PAGE_ID
    _config.ACTIVITY_BUTTON_IDS = {a: v['button_id'] for a, v in activities.items()}
    _config.ACTIVITY_DISPLAY_NAMES = {a: v['display_name'] for a, v in activities.items()}
    _config.ACTIVITY_GROUP_SIZE_REQUIRED = {a: v['group_size_required'] for a, v in activities.items()}
    _config.ACTIVITY_MATCH_PATTERNS = {a: v['match_patterns'] for a, v in activities.items()}

    # Propagate to scraper module (imported these names at startup)
    _scraper_module.BOOKING_BASE_URL = _config.BOOKING_BASE_URL
    _scraper_module.BOOKING_CF_URL = _config.BOOKING_CF_URL
    _scraper_module.ACTIVE_CENTER_SLUG = slug
    _scraper_module.ACTIVITY_MATCH_PATTERNS = _config.ACTIVITY_MATCH_PATTERNS
    _scraper_module.ACTIVITY_BUTTON_IDS = _config.ACTIVITY_BUTTON_IDS
    _scraper_module.PAGE_ID = _config.PAGE_ID

    return jsonify({
        'success': True,
        'center': center,
        'booking_url': _config.BOOKING_BASE_URL,
    })


@app.route('/screenshots/<filename>')
def serve_screenshot(filename):
    """Serve screenshot files"""
    return send_from_directory('screenshots', filename)


@app.route('/api/select-slot', methods=['POST'])
def select_slot():
    """Select a time slot and get ContactInfo page fields"""
    try:
        data = request.json or {}
        activity_type = data.get('activity_type')
        slot_data = data.get('slot_data')
        group_size = int(data.get('group_size', 2))
        
        # Validate required fields
        if not activity_type or not slot_data:
            return jsonify({
                'success': False,
                'message': 'Activity type and slot data are required',
                'error_type': 'validation_error'
            }), 400
        
        # Validate slot_data structure
        required_slot_fields = ['queue_id', 'date_time', 'time_hash']
        missing_fields = [field for field in required_slot_fields if field not in slot_data]
        if missing_fields:
            return jsonify({
                'success': False,
                'message': f'Missing required fields in slot data: {", ".join(missing_fields)}',
                'error_type': 'validation_error',
                'missing_fields': missing_fields
            }), 400
        
        # Use a per-session scraper for the booking flow so each user's
        # slot selection state is isolated from other users.
        sid = _session_id()
        scraper = get_booking_scraper(sid, activity_type)

        # Use session lock to prevent multiple simultaneous operations
        with session_lock:
            # Initialize if needed
            if not scraper.current_session_id:
                if not scraper.initialize_session():
                    return jsonify({
                        'success': False,
                        'message': 'Failed to initialize session',
                        'error_type': 'session_error'
                    }), 500

            # Get contact info fields
            result = scraper.get_contact_info_fields(activity_type, slot_data, group_size)
        
        if result.get('success'):
            return jsonify(result)
        else:
            status_code = 500
            if result.get('error_type') == 'validation_error':
                status_code = 400
            elif result.get('error_type') == 'authentication_error':
                status_code = 401
            return jsonify(result), status_code
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error selecting slot: {str(e)}\n{error_details}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}',
            'error_type': 'unknown_error'
        }), 500


# Removed duplicate route - /api/select-slot now handles this functionality with proper locking


@app.route('/api/submit-contact', methods=['POST'])
def submit_contact():
    """Submit contact information"""
    try:
        data = request.json or {}
        activity_type = data.get('activity_type')
        field_values = data.get('field_values', {})
        
        if not activity_type:
            return jsonify({
                'success': False,
                'message': 'Activity type is required'
            }), 400
        
        # Continue the booking flow using the same per-session scraper
        sid = _session_id()
        scraper = get_booking_scraper(sid, activity_type)

        # Use session lock to prevent multiple simultaneous operations
        with session_lock:
            # Submit contact info
            result = scraper.submit_contact_info(activity_type, field_values)
        
        if result.get('success'):
            return jsonify(result)
        else:
            status_code = 500
            if result.get('error_type') == 'validation_error':
                status_code = 400
            elif result.get('error_type') == 'authentication_error':
                status_code = 401
            return jsonify(result), status_code
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error submitting contact info: {str(e)}\n{error_details}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500


@app.route('/api/check-now', methods=['POST'])
def check_now():
    """Manually check for available slots right now"""
    try:
        data = request.json or {}
        activity_type = data.get('activity_type', 'badminton-16+')
        group_size = int(data.get('group_size', 2))
        
        # Use the shared scraper for check-now (same session as monitoring loop)
        scraper = get_shared_scraper(activity_type)

        # Use session lock to prevent multiple simultaneous operations
        with session_lock:
            # Initialize if needed
            if not scraper.current_session_id:
                if not scraper.initialize_session():
                    return jsonify({
                        'success': False,
                        'message': 'Failed to initialize session',
                        'error_type': 'session_error'
                    }), 500

            # Get all available slots (with navigation)
            result = scraper.get_available_slots(activity_type, group_size, navigate=True)

        # Extract results
        slots = result.get('slots', []) if result.get('success') else []
        screenshot_path = result.get('screenshot')

        # Send Telegram notification if slots found (single check)
        if slots:
            telegram.notify_slot_found(slots, activity_type)

        # Update monitoring process state if it exists
        if activity_type in monitoring_processes and screenshot_path:
            monitoring_processes[activity_type]['screenshot'] = screenshot_path
        
        # Return result with proper error handling
        if result.get('success'):
            return jsonify({
                'success': True,
                'slots': slots,
                'screenshot': screenshot_path,
                'message': result.get('message', f'Found {len(slots)} available slot(s)')
            })
        else:
            # Return error with details
            return jsonify({
                'success': False,
                'slots': [],
                'screenshot': screenshot_path,
                'message': result.get('message', 'Failed to check for slots'),
                'error_type': result.get('error_type', 'unknown_error'),
                'status_code': result.get('status_code'),
                'error_details': result.get('error_details')
            }), 500
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Error in manual check: {str(e)}\n{error_details}")
        return jsonify({
            'success': False,
            'slots': [],
            'screenshot': None,
            'message': f'Error: {str(e)}',
            'error_type': 'unknown_error',
            'error_details': str(e)
        }), 500




@app.route('/api/telegram/chat-ids', methods=['GET'])
def get_chat_ids():
    """Return current list of Telegram chat IDs"""
    return jsonify({
        'chat_ids': telegram.chat_ids,
        'telegram_enabled': telegram.enabled
    })


@app.route('/api/telegram/chat-ids', methods=['POST'])
def add_chat_id():
    """Add a new Telegram chat ID"""
    data = request.json or {}
    chat_id = str(data.get('chat_id', '')).strip()
    if not chat_id:
        return jsonify({'success': False, 'message': 'chat_id is required'}), 400

    added = telegram.add_chat_id(chat_id)
    if not added:
        return jsonify({'success': False, 'message': 'Chat ID already exists'}), 409

    save_chat_ids(telegram.chat_ids)
    return jsonify({'success': True, 'chat_ids': telegram.chat_ids})


@app.route('/api/telegram/chat-ids/<chat_id>', methods=['DELETE'])
def delete_chat_id(chat_id):
    """Remove a Telegram chat ID"""
    removed = telegram.remove_chat_id(chat_id)
    if not removed:
        return jsonify({'success': False, 'message': 'Chat ID not found'}), 404

    save_chat_ids(telegram.chat_ids)
    return jsonify({'success': True, 'chat_ids': telegram.chat_ids})


@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """Receive incoming Telegram updates via webhook.
    When anyone messages the bot they are auto-registered for notifications.
    """
    update = request.get_json(silent=True) or {}

    message = update.get('message') or update.get('edited_message')
    if not message:
        return '', 200
    _handle_telegram_message(message)
    return '', 200


@app.route('/api/telegram/setup-webhook', methods=['POST'])
def setup_webhook():
    """Register this app's URL as the Telegram webhook.
    Call this once after deploying with body: {"base_url": "https://your-app.run.app"}
    """
    if not telegram.enabled:
        return jsonify({'success': False, 'message': 'Telegram bot not configured'}), 400

    data = request.get_json(silent=True) or {}
    base_url = data.get('base_url', '').rstrip('/')
    if not base_url:
        return jsonify({'success': False, 'message': 'base_url is required'}), 400

    webhook_url = f"{base_url}/telegram/webhook"
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{telegram.bot_token}/setWebhook",
            json={"url": webhook_url, "allowed_updates": ["message"]},
            timeout=10,
        )
        result = resp.json()
        if result.get('ok'):
            return jsonify({'success': True, 'webhook_url': webhook_url})
        return jsonify({'success': False, 'message': result.get('description', 'Unknown error')}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


if __name__ == '__main__':
    try:
        import socket
        # Get WSL IP address
        hostname = socket.gethostname()
        try:
            wsl_ip = socket.gethostbyname(hostname)
        except:
            wsl_ip = FLASK_HOST
        
        print("=" * 60)
        print("Ottawa Rec Booking App")
        print("=" * 60)
        print(f"Server running on:")
        print(f"  http://{wsl_ip}:{FLASK_PORT}")
        print(f"  http://localhost:{FLASK_PORT}")
        print("=" * 60)
        print("\nPress Ctrl+C to stop the server\n")
        
        # Use PORT environment variable if available (for platforms like Railway, Render, etc.)
        port = int(os.environ.get('PORT', FLASK_PORT))
        app.run(debug=False, host=FLASK_HOST, port=port, use_reloader=False)
    except OSError as e:
        if "Address already in use" in str(e) or "address is already in use" in str(e).lower():
            logger.error(f"Port {FLASK_PORT} is already in use")
            print(f"\nERROR: Port {FLASK_PORT} is already in use!")
            print(f"Either stop the other process or change FLASK_PORT in your .env file")
        else:
            logger.error(f"Failed to start server: {str(e)}")
            print(f"\nERROR: Failed to start server: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        print(f"\nERROR: {e}")

