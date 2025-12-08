#!/usr/bin/env python3
"""
Simple script to run the Flask app with better error handling
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app import app
    from config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG
    
    print("=" * 60)
    print("Ottawa Rec Booking App")
    print("=" * 60)
    print(f"Starting server on http://{FLASK_HOST}:{FLASK_PORT}")
    print(f"Debug mode: {FLASK_DEBUG}")
    print("=" * 60)
    print("\nPress Ctrl+C to stop the server\n")
    
    app.run(
        debug=FLASK_DEBUG,
        host=FLASK_HOST,
        port=FLASK_PORT,
        use_reloader=False  # Disable reloader to avoid issues
    )
except KeyboardInterrupt:
    print("\n\nServer stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"\n\nERROR: Failed to start server: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

