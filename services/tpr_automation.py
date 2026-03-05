"""
TPR Form Automation using Playwright.
Automates filling out the CMU Transaction Processing Request form.

Field IDs captured from live form at https://xforms.andrew.cmu.edu/SATransactionProcessingRequest
"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Optional, Callable

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

from config.settings import CMUConfig
from config.constants import (
    ORG_NAME, ACCOUNT_TYPE, TRANSACTION_TYPE,
    PREPARER_FIRST_NAME, PREPARER_WHO_FORMAT
)
from models.receipt import ReceiptData, TPRRequest
from utils.helpers import extract_one_word_descriptor, sanitize_for_tpr

logger = logging.getLogger(__name__)


# ============================================================================
# FORM FIELD IDS (Captured from live Jadu XForms)
# ============================================================================

# Page 1: Preparer Details
FIELD_IDS = {
    # Page 1
    "andrew_id_lookup": "qae896d04da6e81578b89e320172bb751104a1e31_0_0",
    "preparer_first_name": "qac43c11b9b56146cfce8da9b0946eafb876f41bd",
    "on_behalf_of_someone_else": "qff044216c0c0371873df8535121951a2e30b5ae6",
    "transaction_type": "qf79cf22d534268b1bf2b1f6f0fc3f109d6221475",
    "student_org_business": "q6dcbaa2e5c4c019f0ed81c6e3ab0a069b2d7186a",
    "organization_name": "q19da8dcd4690bc026113caa40404b16790f15cf3",
    "organization_name_other": "qbad1b8b97d066876a5afdc56db4294e015052de6",
    "account_charged": "qdefce2003f32081f8a2a64148773a5a1ba9b41b3",
    "amount_page1": "qb40d9429fb314cb6e741cc15dc77ad2c060e7af3",
    "travel_expenses": "qaece189b0a164fc94f7b00751eac4baa171bf8eb",
    "tartan_connect_event": "q354dd4822765324b10468f7601f78ea7f354fced",
    
    # Page 2: Purchasing or Event Information
    "who_field": "qb9571a2cd8618eb25927bc45f3b58b504e1649a7",
    "what_purchased": "q0b80d825b1457a1e2303832cda4243463d13a4f8",
    "when_field": "qbe1ba78bfbb4435ec9743140fb9f002c8027429a",
    "where_field": "q7cf7174a424f3065554164aad1abaf5b24554877",
    "why_field": "q400872c66f4e818772a925e16a974b93ac0f4f53",
    "printing_services": "q8ebb6bca519bb54e1c45d50673a5f1a1e5752bde",
    # Food purchase fields
    "food_attendee_count": "q3a4d41749358f266ed855aeb3d29ac79afd2e6ad",  # Dropdown: Less than or equal to 5 / More than 5
    "food_attendee_names": "q43868a4c9a5da5fa93e4ea60bae23046f3b88e68",  # Text field for names (<=5)
    "food_attendee_number": "q68057f6d44c693f717a1d92b7d559aa4b6447eae",  # Number field for count (>5)
    
    # Page 3: PCard Receipt Details
    "vendor_name": "qf0143afcebb86ad38a15fcca1a60043d52bcb94e",
    "receipt_description": "q668d87b3d25ac6e0d77ef6c03a9be782d3c3640c",
    "receipt_date": "q41fe277b0069737326c5faaca030e72016394e03",
    "receipt_total": "q7d92985271b94b1973232fe9c067c2b92921e138",
    "received_goods": "q858fbb6a128a9eb779b71c2a37677dc11dbf3317",
    "gift_or_prize": "q038d1874a2b91c02a871d70276ab568526f79553",
    "add_another_receipt": "qbdedddc80be3684bb95f4cc1b3705c5af1d73d84",
}

# Navigation selectors
NAV_NEXT = "button.button--primary, .button--primary"
NAV_PREV = "button.button--secondary, .button--secondary"
NAV_SUBMIT = "button.button--primary"  # On review page

# Login selectors
LOGIN_USERNAME = "#username"
LOGIN_PASSWORD = "#passwordinput"
LOGIN_BUTTON = ".loginbutton, input.loginbutton"


class TPRFormAutomation:
    """
    Automates the CMU Transaction Processing Request form.
    
    The form has 4 pages:
    1. Preparer Details - Organization, account, amount
    2. Purchasing/Event Info - Who, What, When, Where, Why
    3. Receipt Details - Vendor, date, amount, upload
    4. Review - Human reviews and submits
    """
    
    def __init__(self, headless: bool = False):
        """
        Initialize TPR automation.
        
        Args:
            headless: Whether to run browser in headless mode.
                     Default False so user can observe and handle 2FA.
        """
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._notify_callback: Optional[Callable] = None
    
    def set_notify_callback(self, callback: Callable):
        """Set callback function for status updates (e.g., Slack messages)."""
        self._notify_callback = callback
    
    async def _notify(self, message: str):
        """Send a notification via callback if set."""
        logger.info(message)
        if self._notify_callback:
            await self._notify_callback(message)
    
    async def start(self):
        """Start the browser using persistent Chrome profile for saved sessions."""
        playwright = await async_playwright().start()
        
        # Use persistent context with Chrome profile for automatic login
        # This preserves cookies and session data between runs
        chrome_profile_path = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
        user_data_dir = Path.home() / ".playwright_chrome_profile"  # Separate profile to avoid conflicts
        
        self.context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=self.headless,
            slow_mo=100,  # Slow down for visibility
            channel="chrome",  # Use installed Chrome instead of Chromium
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        logger.info("Browser started with persistent profile")
    
    async def stop(self):
        """Close the browser."""
        if self.browser:
            await self.browser.close()
            logger.info("Browser closed")
    
    async def login(self, andrew_id: str = None, password: str = None) -> bool:
        """
        Navigate to TPR form and handle CMU login.
        
        Args:
            andrew_id: CMU Andrew ID (defaults to config)
            password: CMU password (defaults to config)
            
        Returns:
            True if login successful
        """
        andrew_id = andrew_id or CMUConfig.ANDREW_ID
        password = password or CMUConfig.PASSWORD
        
        if not andrew_id or not password:
            raise ValueError("CMU credentials not configured")
        
        await self._notify("🔐 Navigating to TPR form...")
        await self.page.goto(CMUConfig.TPR_FORM_URL)
        await self.page.wait_for_load_state("networkidle")
        
        try:
            # Look for Sign In button on xForms page
            # Try multiple selectors for the sign in button
            await self.page.wait_for_timeout(1000)  # Wait for page to settle
            
            sign_in_selectors = [
                'button:has-text("Sign in")',
                'a:has-text("Sign in")',
                'text=Sign in',
                'text=SIGN IN',
                '.sign-in-button',
                '[data-action="sign-in"]',
            ]
            
            for selector in sign_in_selectors:
                try:
                    sign_in = await self.page.query_selector(selector)
                    if sign_in and await sign_in.is_visible():
                        await self._notify("🔑 Clicking Sign In...")
                        await sign_in.click()
                        await self.page.wait_for_load_state("networkidle")
                        break
                except Exception:
                    continue
            
            # Wait a moment for Shibboleth login page to load
            await self.page.wait_for_timeout(1000)
            
            # Check for CMU Shibboleth login page (username field)
            username_field = await self.page.query_selector(LOGIN_USERNAME)
            if username_field and await username_field.is_visible():
                await self._notify("🔑 Entering credentials...")
                await username_field.fill(andrew_id)
                
                password_field = await self.page.query_selector(LOGIN_PASSWORD)
                if password_field:
                    await password_field.fill(password)
                
                # Click the login button
                submit_btn = await self.page.query_selector(LOGIN_BUTTON)
                if submit_btn:
                    await self._notify("🔐 Submitting login...")
                    await submit_btn.click()
                    # Don't wait for networkidle here as Duo may redirect
                    await self.page.wait_for_timeout(2000)
            
            # ALWAYS wait for the form to be ready (handles both 2FA and cached sessions)
            await self._notify("⏳ Waiting for TPR form to load (complete 2FA if prompted)...")
            
            # Wait for actual form page by checking for INPUT fields that only exist on the form
            # Use a specific form field ID that's definitely on Page 1
            form_field_selector = f'input#{FIELD_IDS["andrew_id_lookup"]}'
            
            # Poll for form field with extended timeout for manual 2FA
            max_wait_seconds = 300  # 5 minutes for 2FA
            poll_interval = 2  # Check every 2 seconds
            elapsed = 0
            
            while elapsed < max_wait_seconds:
                try:
                    # Check if we're on the form page by looking for the input field
                    # Wrap in try/except because Duo navigation can destroy context
                    form_field = await self.page.query_selector(form_field_selector)
                    
                    # Also check URL to make sure we're past any auth pages
                    current_url = self.page.url
                    is_on_form = 'xforms.andrew.cmu.edu' in current_url and 'duo' not in current_url.lower() and 'shib' not in current_url.lower()
                    
                    if form_field and is_on_form:
                        break
                        
                except Exception as nav_error:
                    # Navigation in progress (Duo redirect, iframe change, etc.)
                    # This is expected during 2FA - just continue polling
                    logger.debug(f"Navigation in progress during 2FA: {nav_error}")
                
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                
                # Notify user periodically
                if elapsed % 30 == 0:
                    await self._notify(f"⏳ Still waiting... ({elapsed}s elapsed). Complete 2FA if prompted.")
            
            if elapsed >= max_wait_seconds:
                await self._notify("❌ Timeout waiting for form - please try again")
                return False
            
            # Extra wait for page to stabilize after navigation
            try:
                await self.page.wait_for_load_state("networkidle")
            except Exception:
                # May fail if still navigating, that's okay
                pass
            await self.page.wait_for_timeout(2000)  # 2 second buffer for stability
            
            await self._notify("✅ Login successful! Form is ready.")
            return True
            
        except Exception as e:
            logger.error(f"Login failed: {e}")
            await self._notify(f"❌ Login failed: {e}")
            return False
    
    async def fill_page_1(self, tpr_request: TPRRequest):
        """
        Fill out Page 1 - Preparer Details.
        """
        await self._notify("📝 Filling Page 1 - Preparer Details...")
        page = self.page
        
        # Click Lookup button to populate preparer info (should be auto-filled)
        lookup_btn = await page.query_selector('.btn--lookup, button:has-text("Lookup")')
        if lookup_btn:
            await lookup_btn.click()
            await page.wait_for_timeout(1000)
        
        # On behalf of someone else? -> No
        await self._select_dropdown(FIELD_IDS["on_behalf_of_someone_else"], "No")
        await page.wait_for_timeout(300)
        
        # Transaction type -> Purchasing Card Cardholder
        await self._select_dropdown(FIELD_IDS["transaction_type"], TRANSACTION_TYPE)
        await page.wait_for_timeout(300)
        
        # Student org business? -> Yes
        await self._select_dropdown(FIELD_IDS["student_org_business"], "Yes")
        await page.wait_for_timeout(500)  # Wait for conditional fields
        
        # Organization Name -> Other (then fill custom name)
        await self._select_dropdown(FIELD_IDS["organization_name"], "Other")
        await page.wait_for_timeout(500)
        
        # Enter org name in "Other" text field
        org_other = await page.query_selector(f'#{FIELD_IDS["organization_name_other"]}')
        if org_other:
            await org_other.fill(ORG_NAME)
        
        # Account charged -> Agency
        await self._select_dropdown(FIELD_IDS["account_charged"], ACCOUNT_TYPE)
        await page.wait_for_timeout(300)
        
        # Amount (total)
        amount_field = await page.query_selector(f'#{FIELD_IDS["amount_page1"]}')
        if amount_field:
            await amount_field.fill(tpr_request.receipt.formatted_amount)
        
        # Travel expenses? -> No
        travel_value = "Yes" if tpr_request.is_travel else "No"
        await self._select_dropdown(FIELD_IDS["travel_expenses"], travel_value)
        
        # TartanConnect event? -> No
        await self._select_dropdown(FIELD_IDS["tartan_connect_event"], "No")
        
        await self._notify("✅ Page 1 complete")
    
    async def go_next_page(self):
        """Click the Next button to go to next page."""
        next_btn = await self.page.query_selector(NAV_NEXT)
        if next_btn:
            await next_btn.click()
            await self.page.wait_for_load_state("networkidle")
            await self.page.wait_for_timeout(500)
    
    async def fill_page_2(self, tpr_request: TPRRequest):
        """
        Fill out Page 2 - Purchasing or Event Information.
        """
        await self._notify("📝 Filling Page 2 - Purchasing Information...")
        page = self.page
        
        # Who (First initial + Last name)
        who_field = await page.query_selector(f'#{FIELD_IDS["who_field"]}')
        if who_field:
            await who_field.fill(sanitize_for_tpr(tpr_request.who_field))
        
        # What (Item description)
        what_field = await page.query_selector(f'#{FIELD_IDS["what_purchased"]}')
        if what_field:
            await what_field.fill(sanitize_for_tpr(tpr_request.what_purchased))
        
        # When (date - use receipt date)
        when_field = await page.query_selector(f'#{FIELD_IDS["when_field"]}')
        if when_field:
            await when_field.fill(tpr_request.receipt.formatted_date)
        
        # Where (vendor name)
        where_field = await page.query_selector(f'#{FIELD_IDS["where_field"]}')
        if where_field:
            await where_field.fill(sanitize_for_tpr(tpr_request.receipt.vendor))
        
        # Why (justification)
        why_field = await page.query_selector(f'#{FIELD_IDS["why_field"]}')
        if why_field:
            await why_field.fill(sanitize_for_tpr(tpr_request.justification))
        
        # Printing services with CMU logo? -> No
        await self._select_dropdown(FIELD_IDS["printing_services"], "No")
        
        # Food purchase handling - attendee count question at bottom of page 2
        if tpr_request.is_food and tpr_request.attendee_count:
            await page.wait_for_timeout(500)  # Wait for form to update
            
            if tpr_request.attendee_count <= 5:
                # Select "Less than or equal to 5"
                await self._select_dropdown(
                    FIELD_IDS["food_attendee_count"], 
                    "Less than or equal to 5"
                )
                await page.wait_for_timeout(500)  # Wait for name field to appear
                
                # Fill in the names
                if tpr_request.attendee_names:
                    names_field = await page.query_selector(
                        f'#{FIELD_IDS["food_attendee_names"]}'
                    )
                    if names_field:
                        await names_field.fill(sanitize_for_tpr(tpr_request.attendee_names))
                        logger.info(f"Entered attendee names: {tpr_request.attendee_names}")
            else:
                # Select "More than 5"
                await self._select_dropdown(
                    FIELD_IDS["food_attendee_count"], 
                    "More than 5"
                )
                await page.wait_for_timeout(500)  # Wait for number field to appear
                
                # Fill in the number
                number_field = await page.query_selector(
                    f'#{FIELD_IDS["food_attendee_number"]}'
                )
                if number_field:
                    await number_field.fill(str(tpr_request.attendee_count))
                    logger.info(f"Entered attendee count: {tpr_request.attendee_count}")
        
        await self._notify("✅ Page 2 complete")
    
    async def fill_page_3(self, tpr_request: TPRRequest):
        """
        Fill out Page 3 - PCard Receipt Details.
        """
        await self._notify("📝 Filling Page 3 - Receipt Details...")
        page = self.page
        receipt = tpr_request.receipt
        
        # Vendor Name
        vendor_field = await page.query_selector(f'#{FIELD_IDS["vendor_name"]}')
        if vendor_field:
            await vendor_field.fill(sanitize_for_tpr(receipt.vendor))
        
        # What (Business Purpose / Item Description)
        desc_field = await page.query_selector(f'#{FIELD_IDS["receipt_description"]}')
        if desc_field:
            await desc_field.fill(sanitize_for_tpr(tpr_request.what_purchased))
        
        # Receipt Date - special date picker that needs keyboard navigation
        date_field = await page.query_selector(f'#{FIELD_IDS["receipt_date"]}')
        if date_field:
            # Parse the date (formatted_date is MM/DD/YYYY)
            date_parts = receipt.formatted_date.split('/')
            if len(date_parts) == 3:
                month, day, year = date_parts
                
                # Click to focus the date field
                await date_field.click()
                await page.wait_for_timeout(200)
                
                # Type month, day, year sequentially (date picker auto-advances)
                await page.keyboard.type(month)
                await page.keyboard.type(day)
                await page.keyboard.type(year)
                await page.wait_for_timeout(200)
                
                logger.info(f"Entered date: {month}{day}{year}")
        
        # Receipt Total
        total_field = await page.query_selector(f'#{FIELD_IDS["receipt_total"]}')
        if total_field:
            await total_field.fill(receipt.formatted_amount)
        
        # Upload receipt document
        if receipt.file_path and receipt.file_path.exists():
            # Find the file input (may be hidden, within a dropzone)
            file_input = await page.query_selector('input[type="file"]')
            if file_input:
                await file_input.set_input_files(str(receipt.file_path))
                await self._notify("📎 Receipt uploaded")
                await page.wait_for_timeout(3000)  # Wait for upload to complete
        
        # Received goods? -> Yes
        await self._select_dropdown(FIELD_IDS["received_goods"], "Yes")
        await page.wait_for_timeout(500)
        
        # Gift or prize? -> No
        await self._select_dropdown(FIELD_IDS["gift_or_prize"], "No")
        await page.wait_for_timeout(500)
        
        # Add another receipt? -> No
        await self._select_dropdown(FIELD_IDS["add_another_receipt"], "No")
        await page.wait_for_timeout(500)
        
        await self._notify("✅ Page 3 complete")
    
    async def wait_for_review(self) -> str:
        """
        Navigate to review page and wait for user to submit.
        
        Returns:
            TPR number after submission
        """
        await self._notify("🔍 TPR form is ready for review!")
        await self._notify("👆 Please review the form in the browser and click 'Submit Form' when ready.")
        await self._notify("⏳ Waiting for your submission...")
        
        try:
            # Poll for confirmation page or TPR number (10 minute timeout)
            # We check for patterns in the page text repeatedly
            start_time = asyncio.get_event_loop().time()
            timeout = 600  # 10 minutes
            
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    # Check for TPR number first
                    tpr_number = await self._extract_tpr_number()
                    if tpr_number != "TPR-UNKNOWN":
                        await self.stop()
                        await self._notify(f"✅ TPR submitted! Number: {tpr_number}")

                        return tpr_number
                    
                    
                except Exception as e:
                    logger.debug(f"Polling error (ignoring): {e}")

                # Wait before next check
                await asyncio.sleep(2)
                
            logger.error("Timed out waiting for TPR submission")
            return ""
            
        except Exception as e:
            logger.error(f"Error waiting for submission: {e}")
            return ""
    
    async def _extract_tpr_number(self) -> str:
        """Extract the TPR number from the confirmation page."""
        page_text = await self.page.content()
        
        # Look for TPR number patterns
        patterns = [
            r'TPR\s*#?\s*:?\s*(\d+)',
            r'TPR(\d{6,})',
            r'Reference\s*#?\s*:?\s*(\d+)',
            r'Confirmation\s*#?\s*:?\s*(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, page_text, re.IGNORECASE)
            if match:
                return f"TPR{match.group(1)}"
        
        return "TPR-UNKNOWN"
    
    async def _select_dropdown(self, field_id: str, value: str):
        """Select a value from a dropdown by field ID."""
        page = self.page
        
        # Try standard select element
        select = await page.query_selector(f'#{field_id}')
        if select:
            tag = await select.evaluate('el => el.tagName')
            if tag == 'SELECT':
                try:
                    # First try by label
                    await select.select_option(label=value, timeout=5000)
                    logger.info(f"Selected '{value}' from dropdown {field_id}")
                    return
                except Exception as e1:
                    try:
                        # Try by value
                        await select.select_option(value=value, timeout=5000)
                        logger.info(f"Selected '{value}' by value from dropdown {field_id}")
                        return
                    except Exception as e2:
                        # Try partial match - get all options and find closest match
                        try:
                            options = await select.evaluate('''el => {
                                return Array.from(el.options).map(o => ({
                                    value: o.value,
                                    text: o.text,
                                    label: o.label
                                }));
                            }''')
                            logger.warning(f"Could not select '{value}' from {field_id}. Available options: {options}")
                            
                            # Try to find partial match
                            value_lower = value.lower()
                            for opt in options:
                                opt_text = (opt.get('text') or '').lower()
                                opt_label = (opt.get('label') or '').lower()
                                if value_lower in opt_text or value_lower in opt_label or opt_text in value_lower:
                                    await select.select_option(value=opt['value'], timeout=5000)
                                    logger.info(f"Selected partial match '{opt['text']}' for '{value}'")
                                    return
                            
                            # If still no match, log and continue (don't crash)
                            await self._notify(f"⚠️ Could not find option '{value}' in dropdown")
                        except Exception as e3:
                            logger.error(f"Failed to get options from {field_id}: {e3}")
        
        # Fallback: click and find option by text
        dropdown = await page.query_selector(f'#{field_id}')
        if dropdown:
            try:
                await dropdown.click()
                await page.wait_for_timeout(300)
                option = await page.query_selector(f'text="{value}"')
                if option:
                    await option.click()
                    logger.info(f"Selected '{value}' via click method")
                    return
            except Exception as e:
                logger.warning(f"Fallback click selection failed for {field_id}: {e}")
    
    async def process_tpr(self, tpr_request: TPRRequest, demo_mode: bool = False) -> str:
        """
        Complete the full TPR form automation workflow.
        
        Args:
            tpr_request: The TPR request data
            demo_mode: If True, skip waiting for submission and return mock TPR number
            
        Returns:
            The TPR number from the confirmation (or mock number in demo mode)
        """
        try:
            await self.start()
            
            # Login
            success = await self.login()
            if not success:
                return ""
            
            # Fill out all pages
            await self.fill_page_1(tpr_request)
            await self.go_next_page()
            
            await self.fill_page_2(tpr_request)
            await self.go_next_page()
            
            await self.fill_page_3(tpr_request)
            await self.go_next_page()
            
            if demo_mode:
                # Demo mode: return mock TPR number without waiting for submission
                await self._notify("🎬 **DEMO MODE** - Skipping actual submission")
                await self._notify("📋 Form is filled and ready for review!")
                await self.page.wait_for_timeout(3000)  # Let user see the form
                mock_tpr = "DEMO-123456"
                logger.info(f"Demo mode: returning mock TPR number {mock_tpr}")
                return mock_tpr
            else:
                # Wait for user to review and submit
                tpr_number = await self.wait_for_review()
                return tpr_number
            
        finally:
            # Keep browser open for review
            pass


async def create_tpr_request(
    receipt: ReceiptData,
    justification: str,
    department: str = None,
    attendee_count: int = None,
    attendee_names: str = None
) -> TPRRequest:
    """
    Create a TPRRequest from receipt data and user input.
    """
    what_purchased = extract_one_word_descriptor(justification)
    
    # Use short_description from VLM if available
    if receipt.short_description:
        what_purchased = receipt.short_description
    
    return TPRRequest(
        receipt=receipt,
        justification=justification,
        what_purchased=what_purchased,
        department=department or receipt.category,
        is_travel=receipt.is_travel,
        is_food=receipt.is_food,
        attendee_count=attendee_count,
        attendee_names=attendee_names,
    )
