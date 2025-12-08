# Deployment Guide

This Flask application can be deployed to various platforms. Choose the one that best fits your needs.

## Option 1: Railway (Recommended - Easiest)

1. **Sign up** at [railway.app](https://railway.app)
2. **Create a new project** and connect your GitHub repository
3. **Add environment variables** in Railway dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `SECRET_KEY`
   - `FLASK_PORT=5000`
   - `FLASK_HOST=0.0.0.0`
   - Other variables from your `.env` file
4. **Railway will auto-detect** Python and deploy
5. **For GitHub Actions deployment:**
   - Get your Railway token from Settings → Tokens
   - Get your Service ID from your service settings
   - Add secrets to GitHub:
     - `RAILWAY_TOKEN`
     - `RAILWAY_SERVICE_ID`

## Option 2: Render

1. **Sign up** at [render.com](https://render.com)
2. **Create a new Web Service** and connect your GitHub repository
3. **Settings:**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python app.py`
   - Environment: Python 3
4. **Add environment variables** in Render dashboard
5. **For GitHub Actions deployment:**
   - Get Deploy Key from your service settings
   - Get Service ID from your service URL
   - Add secrets to GitHub:
     - `RENDER_DEPLOY_KEY`
     - `RENDER_SERVICE_ID`

## Option 3: Fly.io

1. **Install Fly CLI**: `curl -L https://fly.io/install.sh | sh`
2. **Sign up**: `fly auth signup`
3. **Create app**: `fly launch` (follow prompts)
4. **Add secrets**: `fly secrets set KEY=value` for each environment variable
5. **Deploy**: `fly deploy`
6. **For GitHub Actions deployment:**
   - Create API token: `fly tokens create deploy`
   - Add secret to GitHub: `FLY_API_TOKEN`

## Option 4: Heroku (Paid)

1. **Install Heroku CLI**
2. **Login**: `heroku login`
3. **Create app**: `heroku create your-app-name`
4. **Set environment variables**: `heroku config:set KEY=value`
5. **Deploy**: `git push heroku master`

## Environment Variables Required

Make sure to set these in your deployment platform:

```bash
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id
SECRET_KEY=your_secret_key
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
CONTACT_NAME=Your Name
CONTACT_EMAIL=your@email.com
CONTACT_PHONE=1234567890
```

## Notes

- **Port**: Most platforms set `PORT` environment variable. Update `app.py` to use `os.environ.get('PORT', 5000)` if needed
- **Host**: Use `0.0.0.0` to accept connections from all interfaces
- **Screenshots**: The `screenshots/` directory will be created automatically
- **Session Management**: Each deployment gets its own session state

