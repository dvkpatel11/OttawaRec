# telegram_chat_ids_sync.py
import os
import requests
from config import TELEGRAM_BOT_TOKEN

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

def fetch_chat_ids():
    resp = requests.get(f"{BASE_URL}/getUpdates", timeout=10)
    resp.raise_for_status()
    data = resp.json()

    chat_ids = set()
    for update in data.get("result", []):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            continue
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid:
            chat_ids.add(str(cid))
    return sorted(chat_ids)

if __name__ == "__main__":
    ids = fetch_chat_ids()
    print("CHAT IDS:")
    for cid in ids:
        print(cid)
