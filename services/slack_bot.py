"""
Slack Bot using Bolt framework.
Handles receipt processing requests and status notifications.
"""
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

import aiohttp
import aiofiles
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from config.settings import SlackConfig, TEMP_DIR
from models.receipt import ReceiptData, Purchase, SlackMessage
from services.ocr_processor import extract_receipt_data
from services.tpr_automation import TPRFormAutomation, create_tpr_request
from services.google_drive import upload_receipt_to_drive
from services.google_sheets import update_budget, update_tpr_tracking
from utils.helpers import extract_one_word_descriptor, generate_receipt_filename
from services.justification_store import find_matching_justification, save_justification

logger = logging.getLogger(__name__)

# Initialize Slack app
app = AsyncApp(
    token=SlackConfig.BOT_TOKEN,
    signing_secret=SlackConfig.SIGNING_SECRET,
)


class SlackBotService:
    """Main Slack bot service for handling receipt processing."""
    
    def __init__(self, demo_mode: bool = False):
        self.app = app
        self.client: Optional[AsyncWebClient] = None
        self.demo_mode = demo_mode
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Set up event handlers for the Slack app."""
        
        @self.app.event("app_mention")
        async def handle_mention(event, say, client):
            """Handle when the bot is mentioned with a receipt."""
            await self._process_mention(event, say, client)
        
        @self.app.event("message")
        async def handle_dm(event, say, client):
            """Handle direct messages to the bot."""
            # Only process DMs
            if event.get("channel_type") == "im":
                await self._process_mention(event, say, client)
        
        @self.app.action("confirm_submission")
        async def handle_confirm(ack, body, client):
            """Handle confirmation button click."""
            await ack()
            await client.chat_postMessage(
                channel=body["channel"]["id"],
                text="✅ Confirmed! The TPR form is ready for your review. Please submit it in the browser window."
            )
    
    async def _process_mention(self, event: dict, say, client: AsyncWebClient):
        """Process a mention that contains a receipt file."""
        self.client = client
        
        try:
            # Check for file attachments
            files = event.get("files", [])
            if not files:
                await say(
                    "👋 Hi! To process a receipt, please upload a PDF file with your message.\n\n"
                    "Format: `@FinanceBot [receipt.pdf] Brief description of purchase`\n"
                    "Optional: `@FinanceBot [receipt.pdf] Description | Department: Booth`"
                )
                return
            
            # Get the first PDF file
            pdf_file = None
            for f in files:
                if f.get("mimetype") == "application/pdf" or f.get("name", "").endswith(".pdf"):
                    pdf_file = f
                    break
            
            if not pdf_file:
                await say("⚠️ Please upload a PDF receipt file.")
                return
            
            # Parse the message
            message_text = event.get("text", "")
            slack_message = SlackMessage.parse_message(message_text, pdf_file, event)
            
            if not slack_message.justification:
                await say("⚠️ Please include a description of why this purchase was made.")
                return
            
            # Acknowledge receipt
            thread_ts = event.get("ts")
            await say(
                f"📄 Processing receipt: `{pdf_file.get('name')}`\n"
                f"📝 Justification: {slack_message.justification}\n"
                f"⏳ Extracting data...",
                thread_ts=thread_ts
            )
            
            # Download the file
            file_path = await self._download_file(pdf_file, client)
            
            # Extract data from receipt
            try:
                receipt_data = extract_receipt_data(file_path)
            except Exception as e:
                await say(
                    f"❌ Error extracting data from receipt: {e}\n"
                    "Please ensure the PDF is a clear image of a receipt.",
                    thread_ts=thread_ts
                )
                return
            
            # Report extracted data
            food_indicator = "🍕 " if receipt_data.is_food else ""
            await say(
                f"✅ **Extracted Data:**\n"
                f"• Vendor: {receipt_data.vendor}\n"
                f"• Date: {receipt_data.formatted_date}\n"
                f"• Amount: ${receipt_data.formatted_amount}\n"
                f"• Category: {receipt_data.category}\n"
                f"• Description: {receipt_data.short_description}\n"
                f"{food_indicator}Food Purchase: {'Yes' if receipt_data.is_food else 'No'}",
                thread_ts=thread_ts
            )
            
            # If food purchase, ask for attendee information
            attendee_count = None
            attendee_names = None
            
            if receipt_data.is_food:
                # Track last message timestamp to avoid picking up same response twice
                last_seen_ts = thread_ts
                
                # Get user ID from event for pinging
                user_id = event.get("user", "")
                ping = f"<@{user_id}> " if user_id else ""
                
                # Ask for attendee count - ping the user
                await say(
                    f"{ping}🍕 **Food Purchase Detected!**\n\n"
                    "How many people consumed this food?\n"
                    "Please reply with just a number (e.g., `3` or `15`).",
                    thread_ts=thread_ts
                )
                
                # Wait for user response
                count_response, last_seen_ts = await self._wait_for_reply(
                    event.get("channel"), 
                    thread_ts, 
                    client,
                    timeout=120,
                    after_ts=last_seen_ts
                )
                
                if count_response is None:
                    await say(
                        "⏰ No response received. Proceeding without attendee information.\n"
                        "You may need to fill this in manually on the TPR form.",
                        thread_ts=thread_ts
                    )
                else:
                    try:
                        attendee_count = int(count_response.strip())
                        await say(f"✅ Got it - {attendee_count} attendees.", thread_ts=thread_ts)
                        
                        # If 5 or fewer, ask for names
                        if attendee_count <= 5:
                            await say(
                                f"{ping}Since there are {attendee_count} or fewer attendees, "
                                "I need their names.\n\n"
                                "Please reply with all names separated by commas.\n"
                                "Example: `John Smith, Jane Doe, Bob Wilson`",
                                thread_ts=thread_ts
                            )
                            
                            # Wait for names, using the updated last_seen_ts
                            names_response, _ = await self._wait_for_reply(
                                event.get("channel"),
                                thread_ts,
                                client,
                                timeout=120,
                                after_ts=last_seen_ts  # Don't pick up the count response again
                            )
                            
                            if names_response:
                                attendee_names = names_response
                                await say(f"✅ Names recorded: {attendee_names}", thread_ts=thread_ts)
                            else:
                                await say(
                                    "⏰ No names received. You may need to fill this in manually.",
                                    thread_ts=thread_ts
                                )
                    except ValueError:
                        await say(
                            f"⚠️ Couldn't parse '{count_response}' as a number. "
                            "Proceeding without attendee information.",
                            thread_ts=thread_ts
                        )
                        attendee_count = None
            
            await say("🔄 Starting TPR form automation...", thread_ts=thread_ts)
            
            # Create TPR request with food info
            tpr_request = await create_tpr_request(
                receipt=receipt_data,
                justification=slack_message.justification,
                department=slack_message.department,
                attendee_count=attendee_count,
                attendee_names=attendee_names
            )
            
            # Start TPR automation
            async def notify_callback(msg):
                await say(msg, thread_ts=thread_ts)
            
            tpr_automation = TPRFormAutomation(headless=False)
            tpr_automation.set_notify_callback(notify_callback)
            
            tpr_number = await tpr_automation.process_tpr(tpr_request, demo_mode=self.demo_mode)
            
            if not tpr_number:
                await say(
                    "⚠️ TPR form automation completed but could not confirm TPR number. "
                    "Please check the browser and note the TPR number manually.",
                    thread_ts=thread_ts
                )
                return
            
            # Upload receipt to Google Drive
            await say(f"☁️ Uploading receipt to Google Drive...", thread_ts=thread_ts)
            
            receipt_filename = generate_receipt_filename(
                receipt_data.vendor,
                receipt_data.formatted_date,
                receipt_data.amount,
                department=receipt_data.category or slack_message.department or "Misc"
            )
            receipt_link = await upload_receipt_to_drive(file_path, receipt_filename)
            
            # Update spreadsheets
            await say(f"📊 Updating budget spreadsheet...", thread_ts=thread_ts)
            
            purchase = Purchase(
                description=f"{receipt_data.vendor} - {slack_message.justification[:50]}",
                amount=receipt_data.amount,
                vendor=receipt_data.vendor,  # Vendor for display_name
                receipt_link=receipt_link,
                tpr_number=tpr_number,
                department=slack_message.department,
                date=receipt_data.date,
                justification=slack_message.justification
            )
            
            await update_budget(purchase)
            await update_tpr_tracking(purchase)
            
            # Final success message
            await say(
                f"🎉 **All Done!**\n\n"
                f"• TPR Number: `{tpr_number}`\n"
                f"• Receipt uploaded: [View in Drive]({receipt_link})\n"
                f"• Budget sheet: ✅ Updated\n"
                f"• TPR Tracking: ✅ Updated",
                thread_ts=thread_ts
            )
            
            # Ask if this is a recurring purchase
            await say(
                "🔄 Is this a **recurring purchase** (e.g., monthly subscription)?\n"
                "Reply `yes` to save this justification for future purchases from this vendor, "
                "or `no` to continue.",
                thread_ts=thread_ts
            )
            
            # Wait for response
            recurring_response, _ = await self._wait_for_reply(
                event.get("channel"),
                thread_ts,
                client,
                timeout=60,
                after_ts=thread_ts
            )
            
            if recurring_response and recurring_response.strip().lower() in ["yes", "y"]:
                # Save the justification for this vendor
                save_justification(
                    vendor=receipt_data.vendor,
                    justification=slack_message.justification,
                    category=receipt_data.category or "Misc"
                )
                await say(
                    f"✅ Saved! Future purchases from *{receipt_data.vendor}* will suggest:\n"
                    f"_{slack_message.justification}_",
                    thread_ts=thread_ts
                )
            
        except Exception as e:
            logger.exception("Error processing receipt")
            await say(f"❌ An error occurred: {e}")
    
    async def _download_file(self, file_info: dict, client: AsyncWebClient) -> Path:
        """Download a file from Slack."""
        url = file_info.get("url_private")
        filename = file_info.get("name", "receipt.pdf")
        
        # Create temp file path
        file_path = TEMP_DIR / filename
        
        # Download using aiohttp with Slack auth
        headers = {"Authorization": f"Bearer {SlackConfig.BOT_TOKEN}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(await response.read())
                else:
                    raise Exception(f"Failed to download file: {response.status}")
        
        logger.info(f"Downloaded file to: {file_path}")
        return file_path
    
    async def _wait_for_reply(
        self, 
        channel: str, 
        thread_ts: str, 
        client: AsyncWebClient, 
        timeout: int = 120,
        after_ts: str = None
    ) -> tuple[Optional[str], str]:
        """
        Wait for a user reply in a thread.
        
        Args:
            channel: Channel ID
            thread_ts: Thread timestamp to watch
            client: Slack client
            timeout: Seconds to wait for response
            after_ts: Only return messages newer than this timestamp
            
        Returns:
            Tuple of (reply text or None, timestamp of last message seen)
        """
        poll_interval = 2  # seconds
        elapsed = 0
        last_message_ts = after_ts or thread_ts
        
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            
            try:
                # Get thread replies
                result = await client.conversations_replies(
                    channel=channel,
                    ts=thread_ts,
                    limit=20
                )
                
                messages = result.get("messages", [])
                
                # Look for new messages from users (not from bot)
                for msg in reversed(messages):
                    msg_ts = msg.get("ts", "")
                    # Check if this is a newer message and not from the bot
                    if msg_ts > last_message_ts and not msg.get("bot_id"):
                        # Found a user reply - return it with its timestamp
                        return msg.get("text", ""), msg_ts
                        
            except Exception as e:
                logger.warning(f"Error polling for reply: {e}")
        
        return None, last_message_ts
    
    async def send_message(self, channel: str, text: str, thread_ts: str = None):
        """Send a message to a channel."""
        if self.client:
            await self.client.chat_postMessage(
                channel=channel,
                text=text,
                thread_ts=thread_ts
            )
    
    async def start(self):
        """Start the Slack bot."""
        handler = AsyncSocketModeHandler(self.app, SlackConfig.APP_TOKEN)
        logger.info("Starting Slack bot...")
        await handler.start_async()


# Global bot instance
_bot: Optional[SlackBotService] = None


def get_slack_bot(demo_mode: bool = False) -> SlackBotService:
    """Get the global Slack bot instance."""
    global _bot
    if _bot is None:
        _bot = SlackBotService(demo_mode=demo_mode)
    return _bot


async def start_slack_bot(demo_mode: bool = False):
    """Start the Slack bot."""
    bot = get_slack_bot(demo_mode=demo_mode)
    await bot.start()
