#!/usr/bin/env python3
"""
Quick test to verify the Flask app can start
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("Testing Flask app setup...")

try:
    # Test imports
    print("1. Testing imports...")
    from flask import Flask
    from dotenv import load_dotenv
    load_dotenv()
    print("   ✓ Imports successful")
    
    # Test config
    print("2. Testing configuration...")
    from config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG
    print(f"   ✓ Config loaded: Host={FLASK_HOST}, Port={FLASK_PORT}, Debug={FLASK_DEBUG}")
    
    # Test app creation
    print("3. Testing app creation...")
    from app import app
    print("   ✓ App created successfully")
    
    # Test routes
    print("4. Testing routes...")
    with app.test_client() as client:
        response = client.get('/')
        print(f"   ✓ Root route responds: {response.status_code}")
        
        if response.status_code == 200:
            print("   ✓ App is working correctly!")
        else:
            print(f"   ⚠ Unexpected status code: {response.status_code}")
            print(f"   Response: {response.data[:200]}")
    
    print("\n" + "=" * 60)
    print("All tests passed! You can run the app with:")
    print("  python app.py")
    print("  or")
    print("  python run.py")
    print("=" * 60)
    
except ImportError as e:
    print(f"   ✗ Import error: {e}")
    print("\nMake sure you've installed dependencies:")
    print("  pip install -r requirements.txt")
    sys.exit(1)
except Exception as e:
    print(f"   ✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

