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

logger = logging.getLogger(__name__)

# Initialize Slack app
app = AsyncApp(
    token=SlackConfig.BOT_TOKEN,
    signing_secret=SlackConfig.SIGNING_SECRET,
)


class SlackBotService:
    """Main Slack bot service for handling receipt processing."""
    
    def __init__(self):
        self.app = app
        self.client: Optional[AsyncWebClient] = None
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
            await say(
                f"✅ **Extracted Data:**\n"
                f"• Vendor: {receipt_data.vendor}\n"
                f"• Date: {receipt_data.formatted_date}\n"
                f"• Amount: ${receipt_data.formatted_amount}\n\n"
                f"🔄 Starting TPR form automation...",
                thread_ts=thread_ts
            )
            
            # Create TPR request
            tpr_request = await create_tpr_request(
                receipt=receipt_data,
                justification=slack_message.justification,
                department=slack_message.department
            )
            
            # Start TPR automation
            async def notify_callback(msg):
                await say(msg, thread_ts=thread_ts)
            
            tpr_automation = TPRFormAutomation(headless=False)
            tpr_automation.set_notify_callback(notify_callback)
            
            tpr_number = await tpr_automation.process_tpr(tpr_request)
            
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
                receipt_data.amount
            )
            receipt_link = await upload_receipt_to_drive(file_path, receipt_filename)
            
            # Update spreadsheets
            await say(f"📊 Updating budget spreadsheet...", thread_ts=thread_ts)
            
            purchase = Purchase(
                description=f"{receipt_data.vendor} - {slack_message.justification[:50]}",
                amount=receipt_data.amount,
                receipt_link=receipt_link,
                tpr_number=tpr_number,
                department=slack_message.department,
                date=receipt_data.date
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


def get_slack_bot() -> SlackBotService:
    """Get the global Slack bot instance."""
    global _bot
    if _bot is None:
        _bot = SlackBotService()
    return _bot


async def start_slack_bot():
    """Start the Slack bot."""
    bot = get_slack_bot()
    await bot.start()
