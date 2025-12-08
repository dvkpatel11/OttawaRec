# Ottawa Recreation Booking Scraper

Automated booking system for Ottawa recreation facilities, specifically for badminton court reservations at CARDELREC Recreation Complex Goulbourn.

## Features

- 🏸 Automated badminton slot detection and booking
- 📱 Telegram notifications for slot availability and booking status
- 🚀 Simple web interface with start/stop controls
- 🔍 Manual slot checking
- 🔄 Extensible design for other sports (pickleball, etc.)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create Environment File

Copy the example environment file and customize it:

```bash
cp env.example .env
```

Then edit `.env` with your settings. The file should contain:

```bash
# Telegram Configuration (Optional - leave empty if not using Telegram)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Flask Configuration
SECRET_KEY=dev-secret-key-change-in-production
FLASK_DEBUG=False
FLASK_HOST=0.0.0.0
FLASK_PORT=5000

# Logging
LOG_LEVEL=INFO
```

**To enable Telegram notifications:**

1. Create a Telegram bot by messaging [@BotFather](https://t.me/botfather)
2. Get your bot token (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)
3. Get your chat ID:
   - Message [@userinfobot](https://t.me/userinfobot) or [@getidsbot](https://t.me/getidsbot)
   - Or start a chat with your bot and send `/start`, then use [@getidsbot](https://t.me/getidsbot)
4. **Important**: Make sure you've sent `/start` to your bot first!
5. Add them to your `.env` file:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

**Note**: Make sure you copy `env.example` to `.env` (not edit `env.example` directly), as `.env` is gitignored and won't be committed.

### 3. Test the Setup (Optional)

Before running, you can test that everything is set up correctly:

```bash
python test_server.py
```

### 4. Run the Application

```bash
python app.py
```

Or use the run script:

```bash
python run.py
```

The app will be available at `http://localhost:5000` (or the port specified in your `.env` file)

**Troubleshooting:**
- If you get "Address already in use", change `FLASK_PORT` in your `.env` file
- If you get 401 errors, make sure the app is actually running (check the console output)
- Make sure no firewall or antivirus is blocking the connection

## Usage

1. Open the web interface in your browser
2. Click **"Start Monitoring"** to begin checking for available slots
3. The app will:
   - Check for available badminton slots every 5 minutes
   - Send Telegram notifications when slots are found
   - Automatically attempt to book the next available slot
   - Stop monitoring after a successful booking

### Manual Check

Click **"Check Now"** to immediately check for available slots without starting the monitoring loop.

## Configuration

### Environment Variables

Create a `.env` file in the project root with the following variables:

```bash
# Telegram Configuration
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# Flask Configuration
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
SECRET_KEY=your_secret_key_here

# Contact Information (for booking)
CONTACT_NAME=Your Name
CONTACT_EMAIL=your.email@example.com
CONTACT_PHONE=1234567890

# Navigation Delays (for human-like behavior)
NAVIGATION_DELAY_MIN=1.0
NAVIGATION_DELAY_MAX=3.0
```

### Config File

Edit `config.py` to customize:

- Activity types (currently supports badminton-16+, badminton-family, pickleball)
- Request delays
- Default group size
- Group size requirements per sport
- Other settings

## How It Works

1. **Session Initialization**: Creates a session with the booking system
2. **Activity Selection**: Navigates to the badminton booking page
3. **Group Size**: Sets the number of people (default: 1)
4. **Slot Detection**: Parses available time slots from the booking page
5. **Booking**: Automatically submits booking form when slot is found
6. **Notifications**: Sends Telegram alerts at each step

## Important Notes

⚠️ **The booking system only allows one reservation at a time per user.**
- The scraper uses a single session to respect this limitation
- Do not run multiple instances simultaneously

⚠️ **Booking may require login**
- The system may redirect to a login page after selecting a time slot
- You may need to complete the booking manually if authentication is required

## Extending to Other Sports

To add support for other sports:

1. Find the activity button ID from the booking system
2. Add it to `ACTIVITY_BUTTON_IDS` in `config.py`:

```python
ACTIVITY_BUTTON_IDS = {
    'badminton-16+': '2eabeb33-a464-4fd2-af23-6e79329b28d6',
    'your-sport': 'button-id-here',
}
```

3. Use the new activity type in the API calls

## Environment Variables

- `TELEGRAM_BOT_TOKEN`: Telegram bot token (optional)
- `TELEGRAM_CHAT_ID`: Telegram chat ID (optional)
- `SECRET_KEY`: Flask secret key (defaults to dev key)
- `FLASK_DEBUG`: Enable debug mode (true/false)
- `FLASK_HOST`: Host to bind to (default: 0.0.0.0)
- `FLASK_PORT`: Port to bind to (default: 5000)
- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)

## Troubleshooting

- **No slots found**: This is normal - slots may not be available yet
- **Booking fails**: The system may require manual login/authentication
- **Telegram not working**: Check that bot token and chat ID are set correctly
- **Session errors**: The booking system may have changed - check the HTML structure

## License

This project is for personal use only. Please respect the booking system's terms of service.

