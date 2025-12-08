"""
Ottawa Recreation Booking Scraper
Handles navigation and booking for Ottawa recreation facilities
"""
import requests
from requests.exceptions import HTTPError
from bs4 import BeautifulSoup
import re
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from config import (
    BOOKING_BASE_URL, BOOKING_CF_URL, ACTIVITY_BUTTON_IDS, PAGE_ID,
    DEFAULT_GROUP_SIZE, DEFAULT_CULTURE, DEFAULT_UI_CULTURE,
    REQUEST_DELAY, REQUEST_TIMEOUT, NAVIGATION_DELAY_MIN, NAVIGATION_DELAY_MAX
)
import random

logger = logging.getLogger(__name__)


class OttawaRecBookingScraper:
    """Scraper for Ottawa Recreation booking system"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.current_session_id = None
        self.current_page_id = PAGE_ID
        self.last_check_time = None
        self.last_activity_url = None
        
    def _delay(self):
        """Add delay between requests"""
        time.sleep(REQUEST_DELAY)
    
    def _human_delay(self):
        """Add human-like random delay for navigation steps"""
        delay = random.uniform(NAVIGATION_DELAY_MIN, NAVIGATION_DELAY_MAX)
        time.sleep(delay)
    
    def _get_csrf_token(self, html: str) -> Optional[str]:
        """Extract CSRF token from HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        token_input = soup.find('input', {'name': '__RequestVerificationToken'})
        if token_input:
            return token_input.get('value')
        return None
    
    def _extract_session_id(self, html: str) -> Optional[str]:
        """Extract session ID from HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        session_input = soup.find('input', {'name': 'sessionid'})
        if session_input:
            return session_input.get('value')
        return None
    
    def initialize_session(self) -> bool:
        """Initialize session with booking system"""
        try:
            response = self.session.get(
                BOOKING_BASE_URL,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )
            
            # Check for authentication errors in response
            if response.status_code == 401 or response.status_code == 403:
                logger.error(f"Authentication error: HTTP {response.status_code}")
                return False
            
            response.raise_for_status()
            
            # Extract session ID and page ID from response
            self.current_session_id = self._extract_session_id(response.text)
            
            # Try to extract page ID from URL or HTML
            if 'PageId=' in response.url:
                match = re.search(r'PageId=([a-f0-9-]+)', response.url)
                if match:
                    self.current_page_id = match.group(1)
            
            self._human_delay()
            return True
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error initializing session: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize session: {str(e)}")
            return False
    
    def select_activity(self, activity_type: str = 'badminton-16+') -> bool:
        """Navigate to activity selection page and return the page we land on"""
        try:
            if activity_type not in ACTIVITY_BUTTON_IDS:
                logger.error(f"Unknown activity type: {activity_type}")
                return False
            
            button_id = ACTIVITY_BUTTON_IDS[activity_type]
            
            # Navigate to start reservation
            url = f"{BOOKING_CF_URL}/ReserveTime/StartReservation"
            params = {
                'pageId': self.current_page_id,
                'buttonId': button_id,
                'culture': DEFAULT_CULTURE,
                'uiCulture': DEFAULT_UI_CULTURE
            }
            
            response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            
            # Check for authentication errors
            if response.status_code in [401, 403]:
                logger.error(f"Authentication error: HTTP {response.status_code}")
                return False
            
            response.raise_for_status()
            
            # Update session ID if changed
            new_session_id = self._extract_session_id(response.text)
            if new_session_id:
                self.current_session_id = new_session_id
            
            # Store the final URL we landed on
            self.last_activity_url = response.url
            
            self._human_delay()
            return True
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error selecting activity: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Failed to select activity: {str(e)}")
            return False
    
    def set_group_size(self, activity_type: str, group_size: int = DEFAULT_GROUP_SIZE) -> bool:
        """Set group size for reservation - follows actual navigation flow"""
        try:
            button_id = ACTIVITY_BUTTON_IDS.get(activity_type)
            if not button_id:
                logger.error(f"Unknown activity type: {activity_type}")
                return False
            
            # Check if we're already on SlotCountSelection page (from redirect after StartReservation)
            if self.last_activity_url and 'SlotCountSelection' in self.last_activity_url:
                # We're already on the group size page, extract CSRF and submit
                # Get the current page content
                response = self.session.get(self.last_activity_url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
            else:
                # Try to navigate to slot count selection page
                url = f"{BOOKING_CF_URL}/ReserveTime/SlotCountSelection"
                params = {
                    'pageId': self.current_page_id,
                    'buttonId': button_id,
                    'culture': DEFAULT_CULTURE
                }
                
                response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                
                # If 404, check if we can go directly to time selection
                if response.status_code == 404:
                    # Maybe group size is set via form on time selection page
                    # Try to proceed to time selection - group size might be in the form
                    return True
                
                response.raise_for_status()
            
            # Extract CSRF token from current page
            csrf_token = self._get_csrf_token(response.text)
            if not csrf_token:
                # If no CSRF token, maybe we're already past this step
                return True
            
            # Submit group size
            form_data = {
                'sessionid': self.current_session_id,
                'pageid': self.current_page_id,
                'buttonid': button_id,
                'culture': DEFAULT_CULTURE,
                'uiCulture': DEFAULT_UI_CULTURE,
                'reservationCount': str(group_size),
                '__RequestVerificationToken': csrf_token
            }
            
            # Determine the correct URL to POST to
            post_url = self.last_activity_url if (self.last_activity_url and 'SlotCountSelection' in self.last_activity_url) else f"{BOOKING_CF_URL}/ReserveTime/SlotCountSelection"
            
            response = self.session.post(
                post_url,
                data=form_data,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )
            
            # Update last URL after redirect
            if response.url:
                self.last_activity_url = response.url
            
            # If 404 on POST, the endpoint doesn't exist for this activity
            if response.status_code == 404:
                return True  # Continue - group size might be set differently
            
            response.raise_for_status()
            
            # Update last URL after redirect
            if response.url:
                self.last_activity_url = response.url
            
            self._human_delay()
            return True
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                return True  # Endpoint doesn't exist for this activity, continue anyway
            logger.error(f"Failed to set group size: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Failed to set group size: {str(e)}")
            return False
    
    def get_available_slots(
        self, 
        activity_type: str = 'badminton-16+',
        group_size: int = DEFAULT_GROUP_SIZE,
        navigate: bool = True
    ) -> Dict:
        """Get list of available time slots
        
        Args:
            activity_type: Type of activity to check
            group_size: Group size for the reservation
            navigate: Whether to navigate to the activity first (default: True)
        
        Returns:
            Dict with 'success', 'slots', 'message', 'error_type', and optional error details
        """
        try:
            button_id = ACTIVITY_BUTTON_IDS.get(activity_type)
            if not button_id:
                return {
                    'success': False,
                    'slots': [],
                    'message': f'Unknown activity type: {activity_type}',
                    'error_type': 'validation_error'
                }
            
            # Navigate to activity if needed
            if navigate:
                # Initialize session if needed
                if not self.current_session_id:
                    if not self.initialize_session():
                        return {
                            'success': False,
                            'slots': [],
                            'message': 'Failed to initialize session',
                            'error_type': 'session_error'
                        }
                
                # Select activity
                if not self.select_activity(activity_type):
                    return {
                        'success': False,
                        'slots': [],
                        'message': 'Failed to select activity',
                        'error_type': 'navigation_error'
                    }
                
                # Set group size if needed
                if self.last_activity_url and 'SlotCountSelection' in self.last_activity_url:
                    if not self.set_group_size(activity_type, group_size):
                        return {
                            'success': False,
                            'slots': [],
                            'message': 'Failed to set group size',
                            'error_type': 'navigation_error'
                        }
                elif not self.last_activity_url or 'TimeSelection' not in self.last_activity_url:
                    # Try to set group size anyway (will handle 404 if not needed)
                    self.set_group_size(activity_type, group_size)
            
            # Get TimeSelection page
            url = f"{BOOKING_CF_URL}/ReserveTime/TimeSelection"
            params = {
                'culture': DEFAULT_CULTURE,
                'pageId': self.current_page_id,
                'buttonId': button_id
            }
            
            response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            
            # Check for HTTP errors
            if response.status_code in [401, 403]:
                return {
                    'success': False,
                    'slots': [],
                    'message': f'Authentication error: HTTP {response.status_code}',
                    'error_type': 'authentication_error',
                    'status_code': response.status_code
                }
            
            response.raise_for_status()
            
            # Validate that we're on the TimeSelection page
            if 'TimeSelection' not in response.url and 'TimeSelection' not in response.text[:500]:
                return {
                    'success': False,
                    'slots': [],
                    'message': f'Unexpected page: {response.url}',
                    'error_type': 'navigation_error',
                    'url': response.url
                }
            
            # Parse slots
            slots = self._parse_time_slots(response.text)
            self.last_check_time = datetime.now()
            
            # Always save HTML screenshot (even if no slots found)
            screenshot_path = self.save_timeslots_html(activity_type, response.text)
            if screenshot_path:
                # Store screenshot path for this activity
                if not hasattr(self, 'screenshots'):
                    self.screenshots = {}
                self.screenshots[activity_type] = screenshot_path
            
            return {
                'success': True,
                'slots': slots,
                'message': f'Found {len(slots)} available slot(s)' if slots else 'No available slots found',
                'screenshot': screenshot_path
            }
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            logger.error(f"HTTP error getting available slots: {status_code} - {str(e)}")
            return {
                'success': False,
                'slots': [],
                'message': f'HTTP error: {status_code}',
                'error_type': 'http_error',
                'status_code': status_code,
                'error_details': str(e)
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error getting available slots: {str(e)}")
            return {
                'success': False,
                'slots': [],
                'message': f'Network error: {str(e)}',
                'error_type': 'network_error',
                'error_details': str(e)
            }
        except Exception as e:
            logger.error(f"Failed to get available slots: {str(e)}")
            return {
                'success': False,
                'slots': [],
                'message': f'Error: {str(e)}',
                'error_type': 'unknown_error',
                'error_details': str(e)
            }
    
    def save_timeslots_html(self, activity_type: str, html_content: str) -> Optional[str]:
        """Save HTML content of timeslots page to file"""
        try:
            import os
            from datetime import datetime
            
            # Create screenshots directory if it doesn't exist
            screenshots_dir = 'screenshots'
            os.makedirs(screenshots_dir, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"timeslots_{activity_type}_{timestamp}.html"
            filepath = os.path.join(screenshots_dir, filename)
            
            # Save HTML content
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            return filepath
        except Exception as e:
            logger.error(f"Failed to save timeslots HTML: {str(e)}")
            return None
    
    def clear_screenshots(self):
        """Clear all screenshot files"""
        try:
            import os
            import glob
            
            screenshots_dir = 'screenshots'
            if os.path.exists(screenshots_dir):
                # Remove all HTML files in screenshots directory
                pattern = os.path.join(screenshots_dir, '*.html')
                for filepath in glob.glob(pattern):
                    try:
                        os.remove(filepath)
                    except:
                        pass
        except Exception as e:
            logger.error(f"Failed to clear screenshots: {str(e)}")
    
    def _parse_time_slots(self, html: str) -> List[Dict]:
        """Parse available time slots from HTML
        
        Returns empty list if parsing fails or no slots found.
        Validates that HTML contains expected TimeSelection page structure.
        """
        slots = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Validate that we're on a TimeSelection page
        # Look for common indicators of the time selection page
        page_indicators = [
            soup.find('div', class_='date'),
            soup.find(string=re.compile(r'time.*slot', re.I)),
            soup.find('a', class_='time-container')
        ]
        
        # If none of the expected elements are found, this might not be the right page
        if not any(page_indicators):
            # Check for error messages or redirect indicators
            error_indicators = [
                soup.find(string=re.compile(r'error|not found|404', re.I)),
                soup.find('title', string=re.compile(r'error|not found', re.I))
            ]
            if any(error_indicators):
                logger.warning("TimeSelection page may contain errors or be wrong page")
            # Still try to parse in case structure is different
        
        # Find all date sections
        date_sections = soup.find_all('div', class_='date')
        
        if not date_sections:
            # No date sections found - might be empty or wrong page
            logger.debug("No date sections found in TimeSelection page")
            return slots
        
        for date_section in date_sections:
            # Extract date
            date_text_elem = date_section.find('span', class_='header-text')
            if not date_text_elem:
                continue
            
            date_text = date_text_elem.get_text(strip=True)
            
            # Check if date has available slots (not "No more available time slots")
            warning = date_section.find('div', class_='warning-message')
            if warning:
                continue  # Skip dates with no available slots
            
            # Find all time slots
            time_links = date_section.find_all('a', class_='time-container')
            
            for time_link in time_links:
                onclick = time_link.get('onclick', '')
                if 'selectTime' not in onclick:
                    continue
                
                # Extract parameters from onclick: selectTime(queueId, categoryId, dateTime, timeHash)
                # Try multiple regex patterns to handle variations
                patterns = [
                    r'selectTime\((\d+),\s*(null|\d+),\s*"([^"]+)",\s*[\'"]?([a-f0-9]+)[\'"]?\)',
                    r'selectTime\s*\(\s*(\d+)\s*,\s*(null|\d+)\s*,\s*["\']([^"\']+)["\']\s*,\s*["\']?([a-f0-9]+)["\']?\s*\)',
                    r'selectTime\((\d+),(\d+|null),["\']([^"\']+)["\'],["\']?([a-f0-9]+)["\']?\)'
                ]
                
                match = None
                for pattern in patterns:
                    match = re.search(pattern, onclick)
                    if match:
                        break
                
                if match:
                    queue_id = match.group(1)
                    category_id = match.group(2) if match.group(2) != 'null' else None
                    date_time = match.group(3)
                    time_hash = match.group(4)
                    
                    # Validate extracted data
                    if not queue_id or not date_time or not time_hash:
                        logger.warning(f"Invalid slot data extracted: queue_id={queue_id}, date_time={date_time}, time_hash={time_hash}")
                        continue
                    
                    time_text = time_link.find('span', class_='available-time')
                    time_display = time_text.get_text(strip=True) if time_text else date_time
                    
                    slots.append({
                        'date': date_text,
                        'time': time_display,
                        'date_time': date_time,
                        'queue_id': queue_id,
                        'category_id': category_id,
                        'time_hash': time_hash,
                        'full_datetime': f"{date_text} {time_display}"
                    })
                else:
                    logger.debug(f"Could not parse selectTime onclick: {onclick[:100]}")
        
        # Sort by date and time
        slots.sort(key=lambda x: x['date_time'])
        return slots
    
    def book_time_slot(
        self,
        activity_type: str,
        date_time: str,
        time_hash: str,
        queue_id: str,
        category_id: Optional[str] = None,
        group_size: int = DEFAULT_GROUP_SIZE
    ) -> Dict:
        """Book a specific time slot and navigate to ContactInfo page"""
        try:
            button_id = ACTIVITY_BUTTON_IDS.get(activity_type)
            if not button_id:
                return {'success': False, 'message': f'Unknown activity type: {activity_type}'}
            
            # Get the time selection page to get CSRF token
            url = f"{BOOKING_CF_URL}/ReserveTime/TimeSelection"
            params = {
                'culture': DEFAULT_CULTURE,
                'pageId': self.current_page_id,
                'buttonId': button_id
            }
            
            response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            self._human_delay()
            
            csrf_token = self._get_csrf_token(response.text)
            if not csrf_token:
                return {'success': False, 'message': 'Could not get CSRF token'}
            
            # Submit time selection
            form_data = {
                'sessionid': self.current_session_id,
                'pageid': self.current_page_id,
                'buttonid': button_id,
                'culture': DEFAULT_CULTURE,
                'uiCulture': DEFAULT_UI_CULTURE,
                'queueId': queue_id,
                'categoryId': category_id or '',
                'dateTime': date_time,
                'timeHash': time_hash,
                'reservationCount': str(group_size),
                '__RequestVerificationToken': csrf_token
            }
            
            response = self.session.post(
                f"{BOOKING_CF_URL}/ReserveTime/SubmitTimeSelection",
                data=form_data,
                params={'culture': DEFAULT_CULTURE},
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )
            response.raise_for_status()
            self._human_delay()
            
            # Check if we're redirected to ContactInfo page
            if 'ContactInfo' in response.url:
                return {
                    'success': True,
                    'message': 'Time slot selected - on ContactInfo page',
                    'next_step': 'contact_info',
                    'url': response.url,
                    'html': response.text
                }
            elif 'login' in response.url.lower() or 'signin' in response.url.lower():
                return {
                    'success': True,
                    'message': 'Booking initiated - login required',
                    'next_step': 'login',
                    'url': response.url
                }
            elif 'confirm' in response.url.lower() or 'success' in response.url.lower():
                return {
                    'success': True,
                    'message': 'Booking successful!',
                    'url': response.url
                }
            else:
                # Parse response to see what happened
                return {
                    'success': True,
                    'message': 'Time slot selected - check response',
                    'url': response.url,
                    'html_preview': response.text[:500]
                }
        except Exception as e:
            logger.error(f"Failed to book time slot: {str(e)}")
            return {'success': False, 'message': f'Booking failed: {str(e)}'}
    
    def find_next_available_slot(self, activity_type: str = 'badminton-16+', group_size: int = DEFAULT_GROUP_SIZE) -> Optional[Dict]:
        """Find the next available time slot"""
        try:
            # Initialize if needed
            if not self.current_session_id:
                if not self.initialize_session():
                    return None
            
            # Select activity - this will redirect us to the appropriate page
            if not self.select_activity(activity_type):
                return None
            
            # Check where we landed after selecting activity
            # The redirect might take us directly to TimeSelection, or to SlotCountSelection
            if self.last_activity_url:
                if 'SlotCountSelection' in self.last_activity_url:
                    # We landed on group size selection page - set it
                    # This will redirect us to TimeSelection after setting group size
                    self.set_group_size(activity_type, group_size)
                elif 'TimeSelection' in self.last_activity_url:
                    # We're already on time selection - group size will be set when booking
                    pass
                else:
                    # Unknown page - try to navigate to time selection
                    pass
            else:
                # No redirect URL stored - try to set group size (will handle 404 if endpoint doesn't exist)
                self.set_group_size(activity_type, group_size)
            
            # Get available slots (this will navigate to TimeSelection if not already there)
            result = self.get_available_slots(activity_type, group_size, navigate=False)
            
            if result.get('success') and result.get('slots'):
                return result['slots'][0]  # Return earliest available slot
            return None
        except Exception as e:
            logger.error(f"Error finding next available slot: {str(e)}")
            return None
    
    def auto_book_next_available(
        self,
        activity_type: str = 'badminton-16+',
        group_size: int = DEFAULT_GROUP_SIZE
    ) -> Dict:
        """Automatically find and book the next available slot"""
        try:
            slot = self.find_next_available_slot(activity_type, group_size)
            
            if not slot:
                return {
                    'success': False,
                    'message': 'No available slots found'
                }
            
            # Book the slot
            result = self.book_time_slot(
                activity_type=activity_type,
                date_time=slot['date_time'],
                time_hash=slot['time_hash'],
                queue_id=slot['queue_id'],
                category_id=slot.get('category_id'),
                group_size=group_size
            )
            
            if result['success']:
                result['slot'] = slot
            
            return result
        except Exception as e:
            logger.error(f"Error in auto-booking: {str(e)}")
            return {
                'success': False,
                'message': f'Auto-booking failed: {str(e)}'
            }
    
    def get_contact_info_fields(
        self,
        activity_type: str,
        slot_data: Dict,
        group_size: int = DEFAULT_GROUP_SIZE
    ) -> Dict:
        """Select a time slot and get ContactInfo page fields"""
        try:
            # Validate slot data
            required_fields = ['queue_id', 'date_time', 'time_hash']
            for field in required_fields:
                if field not in slot_data:
                    return {
                        'success': False,
                        'message': f'Missing required field in slot data: {field}',
                        'error_type': 'validation_error'
                    }
            
            button_id = ACTIVITY_BUTTON_IDS.get(activity_type)
            if not button_id:
                return {
                    'success': False,
                    'message': f'Unknown activity type: {activity_type}',
                    'error_type': 'validation_error'
                }
            
            # Book the time slot to navigate to ContactInfo page
            booking_result = self.book_time_slot(
                activity_type=activity_type,
                date_time=slot_data['date_time'],
                time_hash=slot_data['time_hash'],
                queue_id=slot_data['queue_id'],
                category_id=slot_data.get('category_id'),
                group_size=group_size
            )
            
            if not booking_result.get('success'):
                return {
                    'success': False,
                    'message': booking_result.get('message', 'Failed to select time slot'),
                    'error_type': 'booking_error',
                    'details': booking_result
                }
            
            # Check if we're on ContactInfo page
            if booking_result.get('next_step') != 'contact_info':
                return {
                    'success': False,
                    'message': f"Unexpected page after booking: {booking_result.get('next_step', 'unknown')}",
                    'error_type': 'navigation_error',
                    'url': booking_result.get('url'),
                    'next_step': booking_result.get('next_step')
                }
            
            # Parse ContactInfo page HTML to extract form fields
            html = booking_result.get('html', '')
            if not html:
                # Try to get the page content
                url = booking_result.get('url')
                if url:
                    response = self.session.get(url, timeout=REQUEST_TIMEOUT)
                    response.raise_for_status()
                    html = response.text
                else:
                    return {
                        'success': False,
                        'message': 'No HTML content available to parse contact fields',
                        'error_type': 'parsing_error'
                    }
            
            # Parse form fields from HTML
            fields = self._parse_contact_info_fields(html)
            csrf_token = self._get_csrf_token(html)
            
            return {
                'success': True,
                'fields': fields,
                'csrf_token': csrf_token,
                'url': booking_result.get('url')
            }
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            logger.error(f"HTTP error getting contact info fields: {status_code}")
            return {
                'success': False,
                'message': f'HTTP error: {status_code}',
                'error_type': 'http_error',
                'status_code': status_code
            }
        except Exception as e:
            logger.error(f"Error getting contact info fields: {str(e)}")
            return {
                'success': False,
                'message': f'Error: {str(e)}',
                'error_type': 'unknown_error'
            }
    
    def _parse_contact_info_fields(self, html: str) -> List[Dict]:
        """Parse contact info form fields from HTML"""
        fields = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Find the contact info form
        form = soup.find('form')
        if not form:
            return fields
        
        # Find all input fields
        inputs = form.find_all(['input', 'select', 'textarea'])
        
        for input_elem in inputs:
            field_name = input_elem.get('name', '')
            if not field_name or field_name == '__RequestVerificationToken':
                continue
            
            field_type = input_elem.get('type', 'text').lower()
            if field_type == 'hidden':
                continue
            
            # Get label
            label = ''
            label_elem = form.find('label', {'for': input_elem.get('id', '')})
            if not label_elem:
                # Try to find label by text before input
                parent = input_elem.find_parent()
                if parent:
                    label_elem = parent.find('label')
            if label_elem:
                label = label_elem.get_text(strip=True)
            
            # Determine field type
            if input_elem.name == 'select':
                field_type = 'select'
                # Get options
                options = []
                for option in input_elem.find_all('option'):
                    option_value = option.get('value', '')
                    option_text = option.get_text(strip=True)
                    if option_value or option_text:
                        options.append({'value': option_value, 'text': option_text})
                field_info = {
                    'name': field_name,
                    'type': 'select',
                    'label': label or field_name,
                    'required': input_elem.has_attr('required'),
                    'options': options
                }
            elif input_elem.name == 'textarea':
                field_info = {
                    'name': field_name,
                    'type': 'textarea',
                    'label': label or field_name,
                    'required': input_elem.has_attr('required'),
                    'placeholder': input_elem.get('placeholder', '')
                }
            else:
                field_info = {
                    'name': field_name,
                    'type': field_type,
                    'label': label or field_name,
                    'required': input_elem.has_attr('required'),
                    'placeholder': input_elem.get('placeholder', '')
                }
            
            fields.append(field_info)
        
        return fields
    
    def submit_contact_info(
        self,
        activity_type: str,
        field_values: Dict
    ) -> Dict:
        """Submit contact information form"""
        try:
            button_id = ACTIVITY_BUTTON_IDS.get(activity_type)
            if not button_id:
                return {
                    'success': False,
                    'message': f'Unknown activity type: {activity_type}',
                    'error_type': 'validation_error'
                }
            
            # Get the current ContactInfo page to get CSRF token
            # We need to be on the ContactInfo page - if not, we can't submit
            # Try to get the page URL from the last booking result or navigate there
            url = f"{BOOKING_CF_URL}/ReserveTime/ContactInfo"
            
            # Try to get the ContactInfo page
            response = self.session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            
            # Check if we're actually on ContactInfo page
            if 'ContactInfo' not in response.url:
                return {
                    'success': False,
                    'message': 'Not on ContactInfo page. Please select a slot first.',
                    'error_type': 'navigation_error',
                    'url': response.url
                }
            
            response.raise_for_status()
            self._human_delay()
            
            # Get CSRF token
            csrf_token = self._get_csrf_token(response.text)
            if not csrf_token:
                return {
                    'success': False,
                    'message': 'Could not get CSRF token from ContactInfo page',
                    'error_type': 'csrf_error'
                }
            
            # Prepare form data
            form_data = {
                'sessionid': self.current_session_id,
                'pageid': self.current_page_id,
                'buttonid': button_id,
                'culture': DEFAULT_CULTURE,
                'uiCulture': DEFAULT_UI_CULTURE,
                '__RequestVerificationToken': csrf_token
            }
            
            # Add field values
            form_data.update(field_values)
            
            # Submit the form
            response = self.session.post(
                f"{BOOKING_CF_URL}/ReserveTime/SubmitContactInfo",
                data=form_data,
                params={'culture': DEFAULT_CULTURE},
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )
            response.raise_for_status()
            self._human_delay()
            
            # Check the result
            if 'confirm' in response.url.lower() or 'success' in response.url.lower():
                return {
                    'success': True,
                    'message': 'Contact information submitted successfully!',
                    'url': response.url,
                    'next_step': 'confirmation'
                }
            elif 'ContactInfo' in response.url:
                # Still on ContactInfo page - might be validation errors
                soup = BeautifulSoup(response.text, 'html.parser')
                error_messages = soup.find_all(['div', 'span'], class_=re.compile(r'error|validation', re.I))
                error_text = ' '.join([e.get_text(strip=True) for e in error_messages if e.get_text(strip=True)])
                
                return {
                    'success': False,
                    'message': error_text or 'Form submission failed. Please check your information.',
                    'error_type': 'validation_error',
                    'url': response.url
                }
            else:
                return {
                    'success': True,
                    'message': 'Contact information submitted',
                    'url': response.url,
                    'next_step': 'unknown'
                }
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response else None
            logger.error(f"HTTP error submitting contact info: {status_code}")
            return {
                'success': False,
                'message': f'HTTP error: {status_code}',
                'error_type': 'http_error',
                'status_code': status_code
            }
        except Exception as e:
            logger.error(f"Error submitting contact info: {str(e)}")
            return {
                'success': False,
                'message': f'Error: {str(e)}',
                'error_type': 'unknown_error'
            }

