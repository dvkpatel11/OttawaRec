"""
Ottawa Recreation Booking Scraper
Handles navigation and booking for Ottawa recreation facilities

Note: As of 2024, racquet sports (Badminton, Pickleball) are now organized 
under the "Gymnasium sports" category in the Ottawa recreation booking system.
This scraper uses direct button IDs, so it bypasses category navigation and 
works regardless of the category structure.
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
    REQUEST_DELAY, REQUEST_TIMEOUT, NAVIGATION_DELAY_MIN, NAVIGATION_DELAY_MAX,
    build_booking_url, build_booking_cf_url
)
import random

logger = logging.getLogger(__name__)


class OttawaRecBookingScraper:
    """Scraper for Ottawa Recreation booking system"""
    
    def __init__(self, center: str = "cardelrec"):
        self.center = center
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.current_session_id = None
        self.current_page_id = PAGE_ID
        self.last_check_time = None
        self.last_activity_url = None
        self.last_page_html = None
        self.activity_button_ids = {}  # Cache button IDs extracted at startup
        # These will be set from the page during initialize_session():
        self.initial_page_url = None  # URL of the initial booking page
        self.booking_base_url = build_booking_url(center)
        self.booking_cf_url = build_booking_cf_url(center)
        
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
    
    def _extract_page_id(self, html: str, url: str = None) -> Optional[str]:
        """Extract page ID from HTML or URL"""
        # First try to extract from URL
        if url and 'PageId=' in url:
            match = re.search(r'[Pp]ageId=([a-f0-9-]+)', url)
            if match:
                return match.group(1)
        
        # Try to extract from HTML - look for hidden inputs or JavaScript variables
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for hidden input with name containing 'page' or 'pageId'
        page_inputs = soup.find_all('input', {'type': 'hidden'})
        for inp in page_inputs:
            name = inp.get('name', '').lower()
            if 'pageid' in name or 'page_id' in name:
                value = inp.get('value')
                if value and re.match(r'^[a-f0-9-]+$', value):
                    return value
        
        # Look for pageId in JavaScript variables
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                # Look for patterns like: var pageId = "...", pageId: "...", "pageId":"..."
                matches = re.findall(r'[Pp]ageId["\']?\s*[:=]\s*["\']([a-f0-9-]+)["\']', script.string)
                if matches:
                    return matches[0]
                # Also try PageId
                matches = re.findall(r'[Pp]ageId["\']?\s*[:=]\s*["\']([a-f0-9-]+)["\']', script.string)
                if matches:
                    return matches[0]
        
        # Look for pageId in data attributes
        elements = soup.find_all(attrs={'data-pageid': True})
        if elements:
            page_id = elements[0].get('data-pageid')
            if page_id and re.match(r'^[a-f0-9-]+$', page_id):
                return page_id
        
        return None
    
    def _parse_booking_page_structure(self, html: str) -> Dict:
        """Parse the booking page to extract navigation structure
        
        Returns a dictionary with:
        - buttons: List of button elements with their IDs and attributes
        - links: List of navigation links with hrefs
        - forms: List of forms with their actions and methods
        - page_type: Type of page (initial, slot_count_selection, time_selection, etc.)
        """
        soup = BeautifulSoup(html, 'html.parser')
        structure = {
            'buttons': [],
            'links': [],
            'forms': [],
            'page_type': 'unknown'
        }
        
        # Determine page type
        if 'TimeSelection' in html or soup.find('div', class_='date'):
            structure['page_type'] = 'time_selection'
        elif 'SlotCountSelection' in html or soup.find('input', {'name': 'reservationCount'}):
            structure['page_type'] = 'slot_count_selection'
        elif 'StartReservation' in html or soup.find_all('button', class_=re.compile(r'activity|sport', re.I)):
            structure['page_type'] = 'initial'
        elif 'ContactInfo' in html:
            structure['page_type'] = 'contact_info'
        
        # Extract all buttons with potential button IDs
        buttons = soup.find_all(['button', 'a', 'input'], attrs={'type': ['button', 'submit']})
        buttons.extend(soup.find_all(['a', 'button'], class_=re.compile(r'btn|button|link', re.I)))
        
        for btn in buttons:
            button_info = {
                'element': str(btn),
                'text': btn.get_text(strip=True),
                'button_id': None,
                'href': None,
                'onclick': None,
                'data_attrs': {}
            }
            
            # Extract button ID from various attributes
            button_id = (btn.get('data-buttonid') or 
                        btn.get('data-button-id') or
                        btn.get('data-id') or
                        btn.get('id'))
            
            if button_id and re.match(r'^[a-f0-9-]+$', str(button_id)):
                button_info['button_id'] = button_id
            
            # Extract href if it's a link
            if btn.name == 'a':
                button_info['href'] = btn.get('href')
            
            # Extract onclick handler
            onclick = btn.get('onclick')
            if onclick:
                button_info['onclick'] = onclick
                # Try to extract button ID from onclick
                match = re.search(r'buttonId["\']?\s*[:=]\s*["\']([a-f0-9-]+)["\']', onclick)
                if match:
                    button_info['button_id'] = match.group(1)
            
            # Extract all data attributes
            for attr in btn.attrs:
                if attr.startswith('data-'):
                    button_info['data_attrs'][attr] = btn.get(attr)
            
            if button_info['button_id'] or button_info['href'] or button_info['onclick']:
                structure['buttons'].append(button_info)
        
        # Extract navigation links
        links = soup.find_all('a', href=re.compile(r'ReserveTime|StartReservation|SlotCount|TimeSelection', re.I))
        for link in links:
            link_info = {
                'href': link.get('href'),
                'text': link.get_text(strip=True),
                'full_url': None
            }
            # Resolve relative URLs
            if link_info['href']:
                if link_info['href'].startswith('http'):
                    link_info['full_url'] = link_info['href']
                elif link_info['href'].startswith('/'):
                    link_info['full_url'] = f"{self.booking_cf_url}{link_info['href']}"
            structure['links'].append(link_info)
        
        # Extract forms
        forms = soup.find_all('form')
        for form in forms:
            form_info = {
                'action': form.get('action'),
                'method': form.get('method', 'get').lower(),
                'inputs': []
            }
            
            # Extract all form inputs
            for inp in form.find_all(['input', 'select', 'textarea']):
                input_info = {
                    'name': inp.get('name'),
                    'type': inp.get('type', 'text'),
                    'value': inp.get('value', ''),
                    'required': inp.has_attr('required')
                }
                form_info['inputs'].append(input_info)
            
            structure['forms'].append(form_info)
        
        return structure
    
    def initialize_session(self) -> bool:
        """Initialize session with booking system"""
        try:
            response = self.session.get(
                self.booking_base_url,
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
            
            # Extract page ID from HTML or URL (prefer HTML as it's more reliable)
            extracted_page_id = self._extract_page_id(response.text, response.url)
            if extracted_page_id:
                old_page_id = self.current_page_id
                self.current_page_id = extracted_page_id
                if old_page_id != extracted_page_id:
                    logger.info(f"Extracted NEW page ID: {self.current_page_id} (was {old_page_id})")
                else:
                    logger.info(f"Extracted page ID matches config: {self.current_page_id}")
            else:
                # Fall back to config value if extraction fails
                logger.warning(f"Could not extract page ID from page HTML/URL, using config value: {self.current_page_id}")
                logger.warning(f"Initial page URL: {response.url}")
                # Save initial page for debugging
                try:
                    self.save_timeslots_html("initial_page_debug", response.text)
                except:
                    pass
            
            # Save initial page HTML for navigation
            self.last_page_html = response.text
            self._save_navigation_step('step1_initial_page', response.text, response.url)
            
            # Store initial page URL (set from actual page)
            self.initial_page_url = response.url
            
            # Extract and set values from the page ONCE at startup
            # These variables are now set from the actual page, not hardcoded
            
            # 1. Extract page ID (already done above, but ensure it's set)
            if not self.current_page_id or self.current_page_id == PAGE_ID:
                # Try to extract again if we're still using default
                extracted_page_id = self._extract_page_id(response.text, response.url)
                if extracted_page_id:
                    self.current_page_id = extracted_page_id
            
            # 2. Extract button IDs for all activities
            extracted_buttons = self._extract_activity_buttons(response.text)
            if extracted_buttons:
                # Update our cached button IDs (set from page)
                self.activity_button_ids.update(extracted_buttons)
                logger.info(f"Extracted {len(extracted_buttons)} activity buttons from page: {list(extracted_buttons.keys())}")
                # Compare with config and warn if different
                for activity_type, extracted_id in extracted_buttons.items():
                    config_id = ACTIVITY_BUTTON_IDS.get(activity_type)
                    if config_id and extracted_id != config_id:
                        logger.warning(f"Button ID mismatch for {activity_type}: config has {config_id}, page has {extracted_id} (using page value)")
            else:
                logger.warning("Could not extract activity buttons from initial page, using config values")
                # Fall back to config values
                self.activity_button_ids = ACTIVITY_BUTTON_IDS.copy()
            
            # 3. Extract base URLs from page if they differ (for future use)
            # The URLs are typically consistent, but we store the actual page URL
            if response.url and response.url != self.booking_base_url:
                # If redirected, update base URL
                base_match = re.search(r'(https?://[^/]+)', response.url)
                if base_match:
                    base = base_match.group(1)
                    if 'frontdesksuite' in base:
                        self.booking_base_url = base + f'/rcfs/{self.center}'
                    elif 'frontdeskqms' in base:
                        self.booking_cf_url = base + f'/rcfs/{self.center}'
            
            # Log session initialization details
            logger.info(f"Session initialized - Session ID: {self.current_session_id[:20] if self.current_session_id else 'None'}..., Page ID: {self.current_page_id}")
            logger.info(f"Initial page URL: {self.initial_page_url}")
            logger.info(f"Button IDs set from page: {list(self.activity_button_ids.keys())}")
            
            self._human_delay()
            return True
        except requests.exceptions.HTTPError as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"HTTP error initializing session: {e.response.status_code}\n{error_details}")
            return False
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Failed to initialize session: {str(e)}\n{error_details}")
            return False
    
    def _extract_activity_buttons(self, html: str) -> Dict[str, str]:
        """Extract button IDs for all activities from the page dynamically
        
        Matches activities by text content and extracts their button IDs.
        Returns a dictionary mapping activity_type to button_id.
        """
        soup = BeautifulSoup(html, 'html.parser')
        activity_buttons = {}
        
        # Activity name mappings for matching
        activity_patterns = {
            'badminton-16+': [r'badminton.*16\+', r'badminton.*adult', r'badminton.*16\s*\+'],
            'badminton-family': [r'badminton.*family'],
            'pickleball': [r'pickleball']
        }
        
        # Find all potential activity buttons/links
        # Look for buttons, links, or clickable divs
        candidates = soup.find_all(['button', 'a', 'div'], 
                                  class_=re.compile(r'btn|button|link|activity|sport|card', re.I))
        candidates.extend(soup.find_all(['button', 'a'], attrs={'data-buttonid': True}))
        
        for candidate in candidates:
            text = candidate.get_text(strip=True).lower()
            
            # Check each activity pattern
            for activity_type, patterns in activity_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, text, re.I):
                        # Found a match, extract button ID
                        button_id = None
                        
                        # Try various attributes
                        button_id = (candidate.get('data-buttonid') or
                                    candidate.get('data-button-id') or
                                    candidate.get('data-id'))
                        
                        # Try onclick handler
                        if not button_id:
                            onclick = candidate.get('onclick')
                            if onclick:
                                match = re.search(r'buttonId["\']?\s*[:=]\s*["\']([a-f0-9-]+)["\']', onclick)
                                if match:
                                    button_id = match.group(1)
                        
                        # Try href parameter
                        if not button_id and candidate.name == 'a':
                            href = candidate.get('href', '')
                            match = re.search(r'buttonId=([a-f0-9-]+)', href)
                            if match:
                                button_id = match.group(1)
                        
                        # Validate button ID format
                        if button_id and re.match(r'^[a-f0-9-]{36}$', button_id):
                            if activity_type not in activity_buttons:
                                activity_buttons[activity_type] = button_id
                                logger.info(f"Extracted button ID for {activity_type}: {button_id} from text: '{candidate.get_text(strip=True)[:50]}'")
                            break
        
        return activity_buttons
    
    def _extract_button_id_from_page(self, html: str, activity_name: str) -> Optional[str]:
        """Extract button ID from the booking page HTML for a given activity name"""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Look for buttons/links with the activity name in their text or data attributes
        # Common patterns: data-buttonid, data-button-id, onclick with buttonId, etc.
        
        # Try to find by activity name in text content
        activity_keywords = {
            'badminton-16+': ['badminton', '16+', 'adult'],
            'badminton-family': ['badminton', 'family'],
            'pickleball': ['pickleball']
        }
        
        keywords = activity_keywords.get(activity_name, [activity_name.replace('-', ' ')])
        
        # Look for buttons/links with data attributes
        for keyword in keywords:
            # Find elements containing the keyword
            elements = soup.find_all(string=re.compile(keyword, re.I))
            for element in elements:
                parent = element.find_parent(['a', 'button', 'div'])
                if parent:
                    # Check for buttonId in various attributes
                    button_id = (parent.get('data-buttonid') or 
                               parent.get('data-button-id') or
                               parent.get('data-id') or
                               parent.get('onclick'))
                    
                    if button_id:
                        # Extract UUID from onclick if present
                        if 'onclick' in str(button_id):
                            match = re.search(r'([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})', str(button_id))
                            if match:
                                return match.group(1)
                        elif re.match(r'^[a-f0-9-]+$', str(button_id)):
                            return button_id
        
        # Look for all buttons/links with buttonId attributes
        all_buttons = soup.find_all(attrs={'data-buttonid': True})
        for btn in all_buttons:
            text = btn.get_text().lower()
            if any(kw.lower() in text for kw in keywords):
                button_id = btn.get('data-buttonid')
                if button_id and re.match(r'^[a-f0-9-]+$', button_id):
                    return button_id
        
        return None
    
    def select_activity(self, activity_type: str = 'badminton-16+') -> bool:
        """Navigate to activity selection page using cached button ID from startup"""
        try:
            # Get button ID from cache (extracted at startup) or fall back to config
            button_id = self.activity_button_ids.get(activity_type) or ACTIVITY_BUTTON_IDS.get(activity_type)
            
            if not button_id:
                logger.error(f"No button ID found for activity: {activity_type}")
                return False
            
            # Verify we have required IDs
            if not self.current_page_id:
                logger.error(f"No page ID available for activity selection")
                return False
            
            # Navigate to StartReservation (this establishes flow state and redirects)
            url = f"{self.booking_cf_url}/ReserveTime/StartReservation"
            params = {
                'pageId': self.current_page_id,
                'buttonId': button_id,
                'culture': DEFAULT_CULTURE,
                'uiCulture': DEFAULT_UI_CULTURE
            }
            
            logger.info(f"Navigating to select activity {activity_type} with buttonId={button_id}")
            
            response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            
            # Check for authentication errors
            if response.status_code in [401, 403]:
                logger.error(f"Authentication error: HTTP {response.status_code}")
                self._save_navigation_step(f'step2_{activity_type}_auth_error', response.text, response.url)
                return False
            
            response.raise_for_status()
            
            # Save this navigation step
            self._save_navigation_step(f'step2_{activity_type}_after_select', response.text, response.url)
            self.last_page_html = response.text
            
            # Update session ID if changed
            new_session_id = self._extract_session_id(response.text)
            if new_session_id:
                self.current_session_id = new_session_id
            
            # Store the final URL we landed on
            self.last_activity_url = response.url
            
            logger.info(f"Successfully navigated - URL: {response.url}")
            
            self._human_delay()
            return True
        except requests.exceptions.HTTPError as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"HTTP error selecting activity {activity_type}: {e.response.status_code}\n{error_details}")
            
            # Save error page HTML for debugging
            if e.response:
                try:
                    self._save_navigation_step(f'step2_{activity_type}_error_{e.response.status_code}', e.response.text, e.response.url)
                    screenshot_path = self.save_timeslots_html(step_name=f"{activity_type}_select_error_{e.response.status_code}", html_content=e.response.text)
                    if screenshot_path:
                        if not hasattr(self, 'screenshots'):
                            self.screenshots = {}
                        self.screenshots[activity_type] = screenshot_path
                except Exception as save_error:
                    logger.error(f"Failed to save error screenshot: {str(save_error)}")
            
            return False
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Failed to select activity {activity_type}: {str(e)}\n{error_details}")
            return False
    
    def set_group_size(self, activity_type: str, group_size: int = DEFAULT_GROUP_SIZE) -> bool:
        """Set group size for reservation - uses cached button ID from startup"""
        try:
            # Use cached button ID or fall back to config
            button_id = self.activity_button_ids.get(activity_type) or ACTIVITY_BUTTON_IDS.get(activity_type)
            if not button_id:
                logger.error(f"Unknown activity type: {activity_type}")
                return False
            
            # Simplified: Check if we're already on SlotCountSelection page
            if self.last_activity_url and 'SlotCountSelection' in self.last_activity_url:
                # We're already on the group size page, get current content
                response = self.session.get(self.last_activity_url, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                self._save_navigation_step(f'step2b_{activity_type}_slot_count_page', response.text, response.url)
                self.last_page_html = response.text
            elif self.last_activity_url and 'TimeSelection' in self.last_activity_url:
                # Already on TimeSelection, group size may be set during booking
                logger.info("Already on TimeSelection page, group size may be set during booking")
                return True
            else:
                # Try to navigate to SlotCountSelection (simplified - just construct URL)
                url = f"{self.booking_cf_url}/ReserveTime/SlotCountSelection"
                params = {
                    'pageId': self.current_page_id,
                    'buttonId': button_id,
                    'culture': DEFAULT_CULTURE
                }
                
                response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                
                # If 404, this step may not be needed for this activity
                if response.status_code == 404:
                    logger.info(f"SlotCountSelection returned 404, skipping group size step for {activity_type}")
                    return True
                
                response.raise_for_status()
                self._save_navigation_step(f'step2b_{activity_type}_slot_count_page', response.text, response.url)
                self.last_page_html = response.text
            
            # Extract CSRF token from current page (simplified)
            csrf_token = self._get_csrf_token(self.last_page_html)
            if not csrf_token:
                logger.info("No CSRF token found, may already be past group size step")
                return True
            
            # Build form data (simplified - standard fields)
            form_data = {
                'sessionid': self.current_session_id,
                'pageid': self.current_page_id,
                'buttonid': button_id,
                'culture': DEFAULT_CULTURE,
                'uiCulture': DEFAULT_UI_CULTURE,
                'reservationCount': str(group_size),
                '__RequestVerificationToken': csrf_token
            }
            
            # POST to SlotCountSelection endpoint (simplified)
            post_url = self.last_activity_url if (self.last_activity_url and 'SlotCountSelection' in self.last_activity_url) else f"{self.booking_cf_url}/ReserveTime/SlotCountSelection"
            
            logger.info(f"Submitting group size form to: {post_url}")
            response = self.session.post(
                post_url,
                data=form_data,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True
            )
            
            # If 404 on POST, the endpoint doesn't exist for this activity
            if response.status_code == 404:
                logger.info("Group size POST returned 404, endpoint may not exist for this activity")
                return True  # Endpoint doesn't exist for this activity, continue anyway
            
            response.raise_for_status()
            
            # Save this navigation step
            self._save_navigation_step(f'step2c_{activity_type}_after_group_size', response.text, response.url)
            self.last_page_html = response.text
            
            # Update session ID if changed
            new_session_id = self._extract_session_id(response.text)
            if new_session_id:
                self.current_session_id = new_session_id
            
            # Store the final URL we landed on
            self.last_activity_url = response.url
            
            logger.info(f"Successfully set group size - URL: {response.url}")
            
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
            # Use cached button ID from startup or fall back to config
            button_id = self.activity_button_ids.get(activity_type) or ACTIVITY_BUTTON_IDS.get(activity_type)
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
                    # Get screenshot if available (saved by select_activity on error)
                    screenshot_path = None
                    if hasattr(self, 'screenshots') and activity_type in self.screenshots:
                        screenshot_path = self.screenshots[activity_type]
                    
                    return {
                        'success': False,
                        'slots': [],
                        'message': 'Failed to select activity (check logs for details)',
                        'error_type': 'navigation_error',
                        'screenshot': screenshot_path
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
            
            # Get TimeSelection page - simplified approach
            if self.last_activity_url and 'TimeSelection' in self.last_activity_url:
                # We're already on the time selection page, get it
                logger.info(f"Already on TimeSelection page: {self.last_activity_url}")
                response = self.session.get(self.last_activity_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            else:
                # Construct TimeSelection URL (simplified - use cached button ID)
                url = f"{self.booking_cf_url}/ReserveTime/TimeSelection"
                params = {
                    'culture': DEFAULT_CULTURE,
                    'pageId': self.current_page_id,
                    'buttonId': button_id
                }
                logger.info(f"Navigating to TimeSelection with buttonId={button_id}")
                response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            
            # Check for HTTP errors
            if response.status_code in [401, 403]:
                self._save_navigation_step(f'step3_{activity_type}_auth_error', response.text, response.url)
                return {
                    'success': False,
                    'slots': [],
                    'message': f'Authentication error: HTTP {response.status_code}',
                    'error_type': 'authentication_error',
                    'status_code': response.status_code
                }
            
            response.raise_for_status()
            
            # Save this navigation step
            self._save_navigation_step(f'step3_{activity_type}_time_selection', response.text, response.url)
            self.last_page_html = response.text
            
            # Validate that we're on the TimeSelection page (simplified check)
            if 'TimeSelection' not in response.url and 'TimeSelection' not in response.text[:1000]:
                self._save_navigation_step(f'step3_{activity_type}_unexpected_page', response.text, response.url)
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
            
            # Always save HTML screenshot (even if no slots found or on errors)
            # This helps debug what page was actually returned
            screenshot_path = self.save_timeslots_html(step_name=f'step4_{activity_type}_final_slots', html_content=response.text)
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
            import traceback
            status_code = e.response.status_code if e.response else None
            error_details = traceback.format_exc()
            logger.error(f"HTTP error getting available slots for {activity_type}: {status_code} - {str(e)}\n{error_details}")
            
            # Save error page HTML for debugging (even on 404 or other errors)
            screenshot_path = None
            if e.response:
                try:
                    # Save the error response HTML
                    self._save_navigation_step(f'step3_{activity_type}_error_{status_code}', e.response.text, e.response.url)
                    screenshot_path = self.save_timeslots_html(step_name=f"{activity_type}_error_{status_code}", html_content=e.response.text)
                    if screenshot_path:
                        if not hasattr(self, 'screenshots'):
                            self.screenshots = {}
                        self.screenshots[activity_type] = screenshot_path
                except Exception as save_error:
                    logger.error(f"Failed to save error screenshot: {str(save_error)}")
            
            return {
                'success': False,
                'slots': [],
                'message': f'HTTP error: {status_code}',
                'error_type': 'http_error',
                'status_code': status_code,
                'error_details': str(e),
                'screenshot': screenshot_path
            }
        except requests.exceptions.RequestException as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Network error getting available slots for {activity_type}: {str(e)}\n{error_details}")
            return {
                'success': False,
                'slots': [],
                'message': f'Network error: {str(e)}',
                'error_type': 'network_error',
                'error_details': str(e)
            }
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Failed to get available slots for {activity_type}: {str(e)}\n{error_details}")
            return {
                'success': False,
                'slots': [],
                'message': f'Error: {str(e)}',
                'error_type': 'unknown_error',
                'error_details': str(e)
            }
    
    def _save_navigation_step(self, step_name: str, html: str, url: str = None) -> Optional[str]:
        """Save HTML at each navigation step for debugging
        
        Args:
            step_name: Descriptive name for this step (e.g., 'step1_initial_page')
            html: HTML content to save
            url: Optional URL to include in the saved file
        
        Returns:
            Filepath if successful, None otherwise
        """
        try:
            import os
            from datetime import datetime
            
            # Create screenshots directory if it doesn't exist
            screenshots_dir = 'screenshots'
            os.makedirs(screenshots_dir, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{step_name}_{timestamp}.html"
            filepath = os.path.join(screenshots_dir, filename)
            
            # Add URL as comment at top of HTML if provided
            html_to_save = html
            if url:
                html_to_save = f"<!-- Navigation Step: {step_name}\nURL: {url}\nTimestamp: {timestamp}\n-->\n{html}"
            
            # Save HTML content
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_to_save)
            
            logger.info(f"Saved navigation step: {step_name} to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to save navigation step {step_name}: {str(e)}")
            return None
    
    def save_timeslots_html(self, activity_type: str = None, html_content: str = None, step_name: str = None) -> Optional[str]:
        """Save HTML content to file
        
        Args:
            activity_type: Activity type (optional, for backward compatibility)
            html_content: HTML content to save
            step_name: Step name (optional, if provided uses this instead of activity_type)
        
        Returns:
            Filepath if successful, None otherwise
        """
        try:
            import os
            from datetime import datetime
            
            # Create screenshots directory if it doesn't exist
            screenshots_dir = 'screenshots'
            os.makedirs(screenshots_dir, exist_ok=True)
            
            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            if step_name:
                filename = f"{step_name}_{timestamp}.html"
            elif activity_type:
                filename = f"timeslots_{activity_type}_{timestamp}.html"
            else:
                filename = f"page_{timestamp}.html"
            
            filepath = os.path.join(screenshots_dir, filename)
            
            # Save HTML content
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            return filepath
        except Exception as e:
            logger.error(f"Failed to save HTML: {str(e)}")
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
            # Use cached button ID from startup or fall back to config
            button_id = self.activity_button_ids.get(activity_type) or ACTIVITY_BUTTON_IDS.get(activity_type)
            if not button_id:
                return {'success': False, 'message': f'Unknown activity type: {activity_type}'}
            
            # Get the time selection page to get CSRF token
            url = f"{self.booking_cf_url}/ReserveTime/TimeSelection"
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
                f"{self.booking_cf_url}/ReserveTime/SubmitTimeSelection",
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
            
            # Use cached button ID from startup or fall back to config
            button_id = self.activity_button_ids.get(activity_type) or ACTIVITY_BUTTON_IDS.get(activity_type)
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
            # Use cached button ID from startup or fall back to config
            button_id = self.activity_button_ids.get(activity_type) or ACTIVITY_BUTTON_IDS.get(activity_type)
            if not button_id:
                return {
                    'success': False,
                    'message': f'Unknown activity type: {activity_type}',
                    'error_type': 'validation_error'
                }
            
            # Get the current ContactInfo page to get CSRF token
            # We need to be on the ContactInfo page - if not, we can't submit
            # Try to get the page URL from the last booking result or navigate there
            url = f"{self.booking_cf_url}/ReserveTime/ContactInfo"
            
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
                f"{self.booking_cf_url}/ReserveTime/SubmitContactInfo",
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

