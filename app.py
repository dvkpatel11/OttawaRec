from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from scraper import OttawaRecBookingScraper
from telegram_notifier import TelegramNotifier
from config import FLASK_SECRET_KEY, FLASK_DEBUG, FLASK_HOST, FLASK_PORT, LOG_LEVEL
import threading
import time

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

# Configure logging - only errors
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - ERROR - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress werkzeug INFO logs for successful requests (only log errors)
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# Initialize components
telegram = TelegramNotifier()

# Global state - track multiple monitoring processes
monitoring_processes = {}  # {activity_type: {'thread': thread, 'active': bool, 'group_size': int, 'result': dict, 'screenshot': str}}

# Separate scraper instances per activity type to avoid session conflicts
scrapers = {}  # {activity_type: OttawaRecBookingScraper instance}

def get_scraper(activity_type: str = None):
    """Get or create a scraper instance for an activity type"""
    # For API routes that don't specify activity, use a default
    if not activity_type:
        activity_type = 'default'
    
    if activity_type not in scrapers:
        scraper = OttawaRecBookingScraper()
        scraper.clear_screenshots()
        scrapers[activity_type] = scraper
    
    return scrapers[activity_type]

# Initialize default scraper for backward compatibility
scraper = get_scraper('default')

# Session lock to prevent multiple simultaneous bookings
import threading
session_lock = threading.Lock()


def monitor_loop(activity_type: str = 'badminton-16+', group_size: int = 2):
    """Background monitoring loop for a specific activity"""
    global monitoring_processes
    
    # Get dedicated scraper instance for this activity type
    scraper = get_scraper(activity_type)
    
    # Initialize session outside the lock to allow parallel monitoring
    # The lock will be used for actual operations, not initialization
    if not scraper.initialize_session():
        logger.error(f"Failed to initialize scraper session for {activity_type}")
        telegram.notify_error(f"Failed to initialize booking session for {activity_type}")
        if activity_type in monitoring_processes:
            monitoring_processes[activity_type]['active'] = False
        return
    
    check_count = 0
    # Don't send app started message - too many notifications
    while monitoring_processes.get(activity_type, {}).get('active', False):
        try:
            check_count += 1
            
            # Use session lock for slot checking
            with session_lock:
                # Re-initialize session if needed (session may have expired)
                if not scraper.current_session_id:
                    if not scraper.initialize_session():
                        logger.error(f"Failed to re-initialize session for {activity_type}")
                        telegram.notify_error(f"Failed to re-initialize session for {activity_type}")
                        monitoring_processes[activity_type]['last_error'] = {
                            'message': 'Failed to re-initialize session',
                            'error_type': 'session_error'
                        }
                        # Wait before retrying
                        time.sleep(60)
                        continue
                
                # Get all available slots (with navigation)
                result = scraper.get_available_slots(activity_type, group_size, navigate=True)
                slots = result.get('slots', []) if result.get('success') else []
                
                # Update screenshot in process state
                if result.get('screenshot'):
                    monitoring_processes[activity_type]['screenshot'] = result['screenshot']
                elif hasattr(scraper, 'screenshots') and activity_type in scraper.screenshots:
                    monitoring_processes[activity_type]['screenshot'] = scraper.screenshots[activity_type]
                
                # Store error info if check failed
                if not result.get('success'):
                    monitoring_processes[activity_type]['last_error'] = {
                        'message': result.get('message', 'Unknown error'),
                        'error_type': result.get('error_type', 'unknown_error'),
                        'status_code': result.get('status_code')
                    }
                    # If it's a session/auth error, try to re-initialize next time
                    if result.get('error_type') in ['session_error', 'authentication_error']:
                        scraper.current_session_id = None
            
            # Check previous slots BEFORE updating (to detect new slots)
            previous_slots = monitoring_processes.get(activity_type, {}).get('slots', [])
            previous_slot_count = len(previous_slots) if previous_slots else 0
            
            # Update slots in monitoring process state (for UI display)
            monitoring_processes[activity_type]['slots'] = slots
            
            if slots:
                # Notify when slots are found
                # Send notification if:
                # 1. First check (check_count == 1), OR
                # 2. We didn't have slots before but now we do (previous_slot_count == 0 and len(slots) > 0), OR
                # 3. We have more slots than before (new slots appeared)
                should_notify = (
                    check_count == 1 or 
                    previous_slot_count == 0 or 
                    len(slots) > previous_slot_count
                )
                
                if should_notify:
                    telegram.notify_slot_found(slots[0])
                # Don't auto-book - let user choose which slot to book via UI
            # Don't notify for no slots - too many messages
            
            # Wait before next check (5 minutes = 300 seconds)
            wait_seconds = 300
            if monitoring_processes.get(activity_type, {}).get('active', False):
                for _ in range(wait_seconds):
                    if not monitoring_processes.get(activity_type, {}).get('active', False):
                        break
                    time.sleep(1)
                    
        except Exception as e:
            logger.error(f"Monitoring error: {str(e)}")
            # Critical: notify on errors
            telegram.notify_error(f"Monitoring error: {str(e)}")
            # Wait a bit before retrying
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
        if activity_type in monitoring_processes and monitoring_processes[activity_type]['active']:
            return jsonify({
                'success': False,
                'message': 'Monitoring is already active for this sport'
            }), 400
        
        # Create new monitoring process
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
        logger.error(f"Failed to start monitoring: {str(e)}")
        activity_type = data.get('activity_type', 'badminton-16+')
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
        
        if activity_type not in monitoring_processes or not monitoring_processes[activity_type]['active']:
            return jsonify({
                'success': False,
                'message': 'Monitoring is not active for this sport'
            }), 400
        
        monitoring_processes[activity_type]['active'] = False
        
        # Optionally clean up scraper instance when monitoring stops
        # (Commented out to preserve session state in case user wants to check manually)
        # if activity_type in scrapers:
        #     del scrapers[activity_type]
        
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
    """Get current status for all processes"""
    global monitoring_processes
    
    processes = {}
    last_check_times = {}
    
    for activity_type, process in monitoring_processes.items():
        screenshot_path = None
        scraper = scrapers.get(activity_type)
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
            'slots': process.get('slots', []),  # Include slots in status response
            'last_error': process.get('last_error')  # Include last error if any
        }
    
    return jsonify({
        'processes': processes,
        'last_check': last_check_times,
        'telegram_enabled': telegram.enabled
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
        
        # Get dedicated scraper instance for this activity type
        scraper = get_scraper(activity_type)
        
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
        logger.error(f"Error selecting slot: {str(e)}")
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
        
        # Get dedicated scraper instance for this activity type
        scraper = get_scraper(activity_type)
        
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
        logger.error(f"Error submitting contact info: {str(e)}")
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
        
        # Get dedicated scraper instance for this activity type
        scraper = get_scraper(activity_type)
        
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
        
        # Update monitoring process if it exists
        if activity_type in monitoring_processes:
            if screenshot_path:
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
        logger.error(f"Error in manual check: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500




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
        
        app.run(debug=False, host=FLASK_HOST, port=FLASK_PORT, use_reloader=False)
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

