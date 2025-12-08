"""
Telegram notification module for booking alerts
"""
import requests
import logging
from typing import Optional
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send notifications via Telegram"""
    
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or TELEGRAM_CHAT_ID
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if self.enabled:
            # Validate token format (should be numbers:letters format)
            if not self.bot_token or ':' not in self.bot_token:
                logger.error("Invalid Telegram bot token format")
                self.enabled = False
            else:
                self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
                # Test the connection
                if not self._test_connection():
                    logger.error("Telegram bot token validation failed")
                    self.enabled = False
    
    def _test_connection(self) -> bool:
        """Test Telegram bot token by calling getMe"""
        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    return True
                else:
                    logger.error(f"Telegram getMe failed: {result.get('description', 'Unknown error')}")
                    return False
            else:
                logger.error(f"Telegram getMe HTTP error: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Failed to test Telegram connection: {str(e)}")
            return False
    
    def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """Send a message to Telegram"""
        if not self.enabled:
            return False
        
        try:
            url = f"{self.base_url}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }
            
            response = requests.post(url, json=data, timeout=10)
            
            # Check response
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    return True
                else:
                    error_desc = result.get('description', 'Unknown error')
                    logger.error(f"Telegram API error: {error_desc}")
                    return False
            else:
                logger.error(f"Telegram API error: HTTP {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Telegram message: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram message: {str(e)}")
            return False
    
    def notify_slot_found(self, slot: dict) -> bool:
        """Notify about a found slot"""
        message = (
            f"🏸 <b>Badminton Slot Found!</b>\n\n"
            f"📅 Date: {slot.get('date', 'N/A')}\n"
            f"⏰ Time: {slot.get('time', 'N/A')}\n"
            f"🕐 Full: {slot.get('full_datetime', 'N/A')}\n\n"
            f"Slot is available for booking!"
        )
        return self.send_message(message)
    
    def notify_booking_success(self, slot: dict, booking_result: dict) -> bool:
        """Notify about reaching booking page"""
        next_step = booking_result.get('next_step', '')
        if next_step == 'contact_info':
            message = (
                f"✅ <b>Reached Booking Page!</b>\n\n"
                f"📅 Date: {slot.get('date', 'N/A')}\n"
                f"⏰ Time: {slot.get('time', 'N/A')}\n"
                f"📝 Status: Time slot selected - on ContactInfo page\n"
                f"Please complete the booking form in the app."
            )
        elif next_step == 'login':
            message = (
                f"✅ <b>Reached Booking Page!</b>\n\n"
                f"📅 Date: {slot.get('date', 'N/A')}\n"
                f"⏰ Time: {slot.get('time', 'N/A')}\n"
                f"📝 Status: Login required to complete booking"
            )
        else:
            message = (
                f"✅ <b>Reached Booking Page!</b>\n\n"
                f"📅 Date: {slot.get('date', 'N/A')}\n"
                f"⏰ Time: {slot.get('time', 'N/A')}\n"
                f"📝 Status: {booking_result.get('message', 'Time slot selected')}\n"
            )
        
        if 'url' in booking_result:
            message += f"\n🔗 <a href='{booking_result['url']}'>View Booking Page</a>"
        
        return self.send_message(message)
    
    def notify_booking_failed(self, error_message: str) -> bool:
        """Notify about booking failure"""
        message = (
            f"❌ <b>Booking Failed</b>\n\n"
            f"Error: {error_message}\n\n"
            f"Please check the app for details."
        )
        return self.send_message(message)
    
    def notify_no_slots(self) -> bool:
        """Notify that no slots were found"""
        message = (
            f"🔍 <b>No Slots Available</b>\n\n"
            f"No badminton slots found at this time.\n"
            f"Will continue checking..."
        )
        return self.send_message(message)
    
    def notify_app_started(self) -> bool:
        """Notify that the app has started"""
        message = (
            f"🚀 <b>Ottawa Rec Booking App Started</b>\n\n"
            f"Now monitoring for available badminton slots..."
        )
        return self.send_message(message)
    
    def notify_error(self, error: str) -> bool:
        """Notify about an error"""
        message = (
            f"⚠️ <b>Error Occurred</b>\n\n"
            f"{error}"
        )
        return self.send_message(message)

