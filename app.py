from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for
from flask_cors import CORS
import os
import logging
from functools import wraps
from dotenv import load_dotenv
from scraper import OttawaRecBookingScraper
from telegram_notifier import TelegramNotifier
from config import FLASK_SECRET_KEY, FLASK_HOST, FLASK_PORT
import threading
import time

load_dotenv()

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)


@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response


logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

AUTH_USERNAME = 'admin'
AUTH_PASSWORD = 'Adminx11!'
VALID_CENTERS = ['cardelrec', 'richcraftkanata']

runtime_config = {
    'sports': [
        {'id': 'badminton-16+', 'name': 'Badminton (16+)', 'groupSizeRequired': True},
        {'id': 'badminton-family', 'name': 'Badminton (Family)', 'groupSizeRequired': False},
        {'id': 'pickleball', 'name': 'Pickleball', 'groupSizeRequired': True}
    ],
    'telegram_chat_ids': [],
    'telegram_phone_numbers': []
}

telegram = TelegramNotifier()
monitoring_processes = {}
scrapers = {}
session_lock = threading.Lock()


def auth_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'message': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return func(*args, **kwargs)

    return wrapper


def process_key(activity_type: str, center: str) -> str:
    return f'{center}:{activity_type}'


def get_scraper(activity_type: str = None, center: str = 'cardelrec'):
    if not activity_type:
        activity_type = 'default'
    key = process_key(activity_type, center)
    if key not in scrapers:
        scraper = OttawaRecBookingScraper(center=center)
        scraper.clear_screenshots()
        scrapers[key] = scraper
    return scrapers[key]


def monitor_loop(activity_type: str = 'badminton-16+', center: str = 'cardelrec', group_size: int = 2):
    key = process_key(activity_type, center)
    scraper = get_scraper(activity_type, center)

    if not scraper.initialize_session():
        logger.error(f"Failed to initialize scraper session for {key}")
        telegram.notify_error(f"Failed to initialize booking session for {activity_type} at {center}")
        if key in monitoring_processes:
            monitoring_processes[key]['active'] = False
        return

    check_count = 0
    while monitoring_processes.get(key, {}).get('active', False):
        try:
            check_count += 1
            with session_lock:
                if not scraper.current_session_id:
                    if not scraper.initialize_session():
                        monitoring_processes[key]['last_error'] = {
                            'message': 'Failed to re-initialize session',
                            'error_type': 'session_error'
                        }
                        time.sleep(60)
                        continue

                result = scraper.get_available_slots(activity_type, group_size, navigate=True)
                slots = result.get('slots', []) if result.get('success') else []

                if result.get('screenshot'):
                    monitoring_processes[key]['screenshot'] = result['screenshot']

                if not result.get('success'):
                    monitoring_processes[key]['last_error'] = {
                        'message': result.get('message', 'Unknown error'),
                        'error_type': result.get('error_type', 'unknown_error'),
                        'status_code': result.get('status_code')
                    }
                    if result.get('error_type') in ['session_error', 'authentication_error']:
                        scraper.current_session_id = None

            previous_slots = monitoring_processes.get(key, {}).get('slots', [])
            previous_slot_count = len(previous_slots) if previous_slots else 0
            monitoring_processes[key]['slots'] = slots

            if slots and (check_count == 1 or previous_slot_count == 0 or len(slots) > previous_slot_count):
                telegram.notify_slot_found(slots, activity_type, center=center)

            for _ in range(300):
                if not monitoring_processes.get(key, {}).get('active', False):
                    break
                time.sleep(1)
        except Exception as e:
            logger.error(f"Monitoring error for {key}: {str(e)}")
            telegram.notify_error(f"Monitoring error for {activity_type} at {center}: {str(e)}")
            time.sleep(60)

    if key in monitoring_processes:
        monitoring_processes[key]['active'] = False


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.form or request.json or {}
        username = data.get('username', '')
        password = data.get('password', '')
        if username == AUTH_USERNAME and password == AUTH_PASSWORD:
            session['authenticated'] = True
            return jsonify({'success': True, 'redirect': '/'}) if request.is_json else redirect(url_for('index'))
        if request.is_json:
            return jsonify({'success': False, 'message': 'Invalid credentials'}), 401
        return redirect(url_for('login', error=1))
    return render_template('login.html')


@app.route('/logout', methods=['POST'])
@auth_required
def logout():
    session.clear()
    return jsonify({'success': True})


@app.route('/', methods=['GET'])
@auth_required
def index():
    return render_template('index.html')


@app.route('/api/config', methods=['GET', 'POST'])
@auth_required
def api_config():
    if request.method == 'GET':
        return jsonify({
            'success': True,
            'sports': runtime_config['sports'],
            'centers': VALID_CENTERS,
            'telegram_phone_numbers': runtime_config['telegram_phone_numbers'],
            'telegram_chat_ids': runtime_config['telegram_chat_ids']
        })

    data = request.json or {}
    if 'telegram_phone_numbers' in data:
        runtime_config['telegram_phone_numbers'] = [str(x).strip() for x in data.get('telegram_phone_numbers', []) if str(x).strip()]
    if 'telegram_chat_ids' in data:
        runtime_config['telegram_chat_ids'] = [str(x).strip() for x in data.get('telegram_chat_ids', []) if str(x).strip()]
        telegram.set_recipients(runtime_config['telegram_chat_ids'], runtime_config['telegram_phone_numbers'])
    return jsonify({'success': True, 'message': 'Configuration updated'})


@app.route('/api/sports', methods=['POST'])
@auth_required
def add_sport():
    data = request.json or {}
    sport_id = (data.get('id') or '').strip()
    name = (data.get('name') or '').strip()
    group_required = bool(data.get('groupSizeRequired', True))

    if not sport_id or not name:
        return jsonify({'success': False, 'message': 'Sport id and name are required'}), 400

    if any(s['id'] == sport_id for s in runtime_config['sports']):
        return jsonify({'success': False, 'message': 'Sport id already exists'}), 400

    runtime_config['sports'].append({'id': sport_id, 'name': name, 'groupSizeRequired': group_required})
    return jsonify({'success': True, 'sports': runtime_config['sports']})


@app.route('/api/start', methods=['POST'])
@auth_required
def start_monitoring():
    data = request.json or {}
    activity_type = data.get('activity_type', 'badminton-16+')
    center = data.get('center', 'cardelrec')
    group_size = int(data.get('group_size', 2))

    if center not in VALID_CENTERS:
        return jsonify({'success': False, 'message': 'Invalid center'}), 400
    if group_size < 1 or group_size > 10:
        return jsonify({'success': False, 'message': 'Group size must be between 1 and 10'}), 400

    key = process_key(activity_type, center)
    if key in monitoring_processes and monitoring_processes[key]['active']:
        return jsonify({'success': False, 'message': 'Monitoring is already active for this sport and center'}), 400

    monitoring_processes[key] = {'active': True, 'group_size': group_size, 'result': None, 'center': center, 'activity_type': activity_type}
    thread = threading.Thread(target=monitor_loop, args=(activity_type, center, group_size), daemon=True)
    thread.start()
    monitoring_processes[key]['thread'] = thread
    return jsonify({'success': True, 'message': 'Monitoring started successfully'})


@app.route('/api/stop', methods=['POST'])
@auth_required
def stop_monitoring():
    data = request.json or {}
    activity_type = data.get('activity_type')
    center = data.get('center', 'cardelrec')

    if not activity_type:
        return jsonify({'success': False, 'message': 'Activity type is required'}), 400

    key = process_key(activity_type, center)
    if key not in monitoring_processes or not monitoring_processes[key]['active']:
        return jsonify({'success': False, 'message': 'Monitoring is not active for this sport/center'}), 400

    monitoring_processes[key]['active'] = False
    return jsonify({'success': True, 'message': 'Monitoring stopped'})


@app.route('/api/status', methods=['GET'])
@auth_required
def status():
    processes = {}
    for key, process in monitoring_processes.items():
        activity_type = process.get('activity_type')
        center = process.get('center', 'cardelrec')
        scraper = scrapers.get(key)
        screenshot_path = process.get('screenshot')
        last_check_time = None

        if scraper:
            if hasattr(scraper, 'screenshots') and activity_type in scraper.screenshots:
                screenshot_path = scraper.screenshots[activity_type]
            if scraper.last_check_time:
                last_check_time = scraper.last_check_time.isoformat()

        processes[key] = {
            'active': process.get('active', False),
            'group_size': process.get('group_size', 2),
            'result': process.get('result'),
            'screenshot': screenshot_path,
            'slots': process.get('slots', []),
            'last_error': process.get('last_error'),
            'center': center,
            'activity_type': activity_type,
            'last_check': last_check_time
        }

    return jsonify({'processes': processes, 'telegram_enabled': telegram.enabled})


@app.route('/screenshots/<filename>')
@auth_required
def serve_screenshot(filename):
    return send_from_directory('screenshots', filename)


@app.route('/api/select-slot', methods=['POST'])
@auth_required
def select_slot():
    data = request.json or {}
    activity_type = data.get('activity_type')
    center = data.get('center', 'cardelrec')
    slot_data = data.get('slot_data')
    group_size = int(data.get('group_size', 2))

    if not activity_type or not slot_data:
        return jsonify({'success': False, 'message': 'Activity type and slot data are required', 'error_type': 'validation_error'}), 400

    scraper = get_scraper(activity_type, center)
    with session_lock:
        if not scraper.current_session_id and not scraper.initialize_session():
            return jsonify({'success': False, 'message': 'Failed to initialize session', 'error_type': 'session_error'}), 500
        result = scraper.get_contact_info_fields(activity_type, slot_data, group_size)

    return jsonify(result), (200 if result.get('success') else 500)


@app.route('/api/submit-contact', methods=['POST'])
@auth_required
def submit_contact():
    data = request.json or {}
    activity_type = data.get('activity_type')
    center = data.get('center', 'cardelrec')
    field_values = data.get('field_values', {})

    if not activity_type:
        return jsonify({'success': False, 'message': 'Activity type is required'}), 400

    scraper = get_scraper(activity_type, center)
    with session_lock:
        result = scraper.submit_contact_info(activity_type, field_values)

    return jsonify(result), (200 if result.get('success') else 500)


@app.route('/api/check-now', methods=['POST'])
@auth_required
def check_now():
    data = request.json or {}
    activity_type = data.get('activity_type', 'badminton-16+')
    center = data.get('center', 'cardelrec')
    group_size = int(data.get('group_size', 2))

    scraper = get_scraper(activity_type, center)
    with session_lock:
        if not scraper.current_session_id and not scraper.initialize_session():
            return jsonify({'success': False, 'message': 'Failed to initialize session', 'error_type': 'session_error'}), 500
        result = scraper.get_available_slots(activity_type, group_size, navigate=True)

    slots = result.get('slots', []) if result.get('success') else []
    screenshot_path = result.get('screenshot')
    if slots:
        telegram.notify_slot_found(slots, activity_type, center=center)

    key = process_key(activity_type, center)
    if key not in monitoring_processes:
        monitoring_processes[key] = {'active': False, 'activity_type': activity_type, 'center': center}
    if screenshot_path:
        monitoring_processes[key]['screenshot'] = screenshot_path
    monitoring_processes[key]['slots'] = slots

    if result.get('success'):
        return jsonify({'success': True, 'slots': slots, 'screenshot': screenshot_path, 'message': result.get('message', f'Found {len(slots)} slot(s)')})

    return jsonify({
        'success': False,
        'slots': [],
        'screenshot': screenshot_path,
        'message': result.get('message', 'Failed to check for slots'),
        'error_type': result.get('error_type', 'unknown_error')
    }), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', FLASK_PORT))
    app.run(debug=False, host=FLASK_HOST, port=port, use_reloader=False)
