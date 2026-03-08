"""
Telegram notification module for booking alerts
"""
import requests
import logging
from typing import Optional, List
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_CHAT_IDS, build_booking_url

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send notifications via Telegram"""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        primary_chat_id = chat_id or TELEGRAM_CHAT_ID
        self.chat_ids: List[str] = TELEGRAM_CHAT_IDS.copy() if TELEGRAM_CHAT_IDS else []
        if primary_chat_id and primary_chat_id not in self.chat_ids:
            self.chat_ids.append(primary_chat_id)
        self.phone_numbers: List[str] = []
        self.enabled = bool(self.bot_token and self.chat_ids)

        if self.enabled:
            if not self.bot_token or ':' not in self.bot_token:
                logger.error("Invalid Telegram bot token format")
                self.enabled = False
            else:
                self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
                if not self._test_connection():
                    logger.error("Telegram bot token validation failed")
                    self.enabled = False

    def set_recipients(self, chat_ids: List[str], phone_numbers: Optional[List[str]] = None):
        self.chat_ids = [str(x).strip() for x in chat_ids if str(x).strip()]
        self.phone_numbers = [str(x).strip() for x in (phone_numbers or []) if str(x).strip()]
        self.enabled = bool(self.bot_token and self.chat_ids)

    def _test_connection(self) -> bool:
        try:
            response = requests.get(f"{self.base_url}/getMe", timeout=5)
            return response.status_code == 200 and response.json().get('ok', False)
        except Exception as e:
            logger.error(f"Failed to test Telegram connection: {str(e)}")
            return False

    def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        if not self.enabled:
            return False

        all_ok = True
        for chat_id in self.chat_ids:
            try:
                response = requests.post(
                    f"{self.base_url}/sendMessage",
                    json={'chat_id': chat_id, 'text': message, 'parse_mode': parse_mode},
                    timeout=10
                )
                if response.status_code != 200 or not response.json().get('ok'):
                    all_ok = False
                    logger.error(f"Telegram API error for chat {chat_id}: {response.text}")
            except Exception as e:
                all_ok = False
                logger.error(f"Failed to send Telegram message to {chat_id}: {str(e)}")
        return all_ok

    def notify_slot_found(self, slots: list, activity_type: str = 'badminton-16+', center: str = 'cardelrec') -> bool:
        from config import ACTIVITY_DISPLAY_NAMES

        activity_name = ACTIVITY_DISPLAY_NAMES.get(activity_type, activity_type)
        booking_url = build_booking_url(center)
        if not slots:
            return False

        slot_lines = []
        for slot in slots:
            full_datetime = slot.get('full_datetime') or f"{slot.get('date', 'N/A')} {slot.get('time', 'N/A')}"
            slot_lines.append(f"• {full_datetime}")
        slots_text = "\n".join(slot_lines)
        recipients = f"\n📞 Recipients: {', '.join(self.phone_numbers)}" if self.phone_numbers else ''
        message = (
            f"🏸 <b>{activity_name} - {len(slots)} Slots Found</b>\n"
            f"🏢 Center: {center}\n\n"
            f"{slots_text}\n\n"
            f"🔗 <a href='{booking_url}'>View & Book</a>"
            f"{recipients}"
        )
        return self.send_message(message)

    def notify_error(self, error: str) -> bool:
        return self.send_message(f"⚠️ <b>Error Occurred</b>\n\n{error}")
