"""
Email webhook service for receiving inbound emails from Mailgun.
Processes forwarded receipt emails and triggers TPR automation via Slack.
"""
import asyncio
import hashlib
import hmac
import logging
import tempfile
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, Form, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

from config.settings import MailgunConfig, TEMP_DIR, SlackConfig
from services.email_to_pdf import email_to_pdf
from services.ocr_processor import extract_receipt_data
from services.justification_store import find_matching_justification, save_justification
from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# FastAPI app for webhook
app = FastAPI(title="Receipt Email Webhook")

# In-memory store for pending email receipts (in production, use Redis/DB)
pending_receipts = {}

# Demo mode flag (set by main.py)
_demo_mode = False

def set_demo_mode(enabled: bool):
    """Set demo mode for email webhook processing."""
    global _demo_mode
    _demo_mode = enabled


def verify_mailgun_signature(
    token: str,
    timestamp: str, 
    signature: str,
    api_key: str
) -> bool:
    """Verify that a webhook request came from Mailgun."""
    if not api_key:
        logger.warning("No Mailgun API key configured, skipping signature verification")
        return True
    
    data = f"{timestamp}{token}"
    expected = hmac.new(
        api_key.encode('utf-8'),
        data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(signature, expected)


async def wait_for_reply(
    client: AsyncWebClient,
    channel: str,
    thread_ts: str,
    after_ts: str,
    timeout: int = 120
) -> tuple[Optional[str], str]:
    """
    Wait for a user reply in a Slack thread.
    
    Returns:
        Tuple of (reply text or None, timestamp of last message seen)
    """
    poll_interval = 2
    elapsed = 0
    last_message_ts = after_ts
    
    while elapsed < timeout:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        
        try:
            result = await client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=20
            )
            
            messages = result.get("messages", [])
            
            for msg in reversed(messages):
                msg_ts = msg.get("ts", "")
                if msg_ts > last_message_ts and not msg.get("bot_id"):
                    return msg.get("text", ""), msg_ts
                    
        except Exception as e:
            logger.warning(f"Error polling for reply: {e}")
    
    return None, last_message_ts


async def process_email_receipt(
    sender: str,
    subject: str,
    receipt_data,
    pdf_path: Path
):
    """
    Process an email receipt through the full Slack interactive flow.
    
    1. Post receipt info to Slack
    2. Ask for justification
    3. If food: ask for attendee count
    4. If count <= 5: ask for names
    5. Trigger TPR automation
    """
    channel = MailgunConfig.NOTIFY_CHANNEL
    if not channel:
        logger.warning("No MAILGUN_NOTIFY_CHANNEL configured")
        return
    
    if not SlackConfig.BOT_TOKEN:
        logger.warning("No Slack bot token configured")
        return
    
    client = AsyncWebClient(token=SlackConfig.BOT_TOKEN)
    
    # Step 1: Post initial receipt info
    if receipt_data:
        initial_msg = (
            f"📧 *New Receipt Email Received*\n\n"
            f"*From:* {sender}\n"
            f"*Subject:* {subject}\n\n"
            f"*Extracted Details:*\n"
            f"• Vendor: {receipt_data.vendor}\n"
            f"• Amount: ${receipt_data.amount:.2f}\n"
            f"• Date: {receipt_data.formatted_date}\n"
            f"• Category: {receipt_data.category or 'Unknown'}\n"
        )
        if receipt_data.is_food:
            initial_msg += "\n🍕 _This appears to be a food purchase_"
    else:
        initial_msg = (
            f"📧 *New Receipt Email Received*\n\n"
            f"*From:* {sender}\n"
            f"*Subject:* {subject}\n\n"
            f"⚠️ Could not extract receipt details automatically.\n"
        )
        raise Exception("Could not extract receipt details automatically. Please print the email and try again.")
    
    try:
        result = await client.chat_postMessage(channel=channel, text=initial_msg)
        thread_ts = result.get("ts")
        last_seen_ts = thread_ts
        logger.info(f"Posted to Slack channel {channel}, thread: {thread_ts}")
    except Exception as e:
        logger.error(f"Failed to post to Slack: {e}")
        return
    
    # Step 2: Check for saved justification or ask for new one
    saved, match_score = find_matching_justification(receipt_data.vendor) if receipt_data else (None, 0)
    auto_approve_threshold = 90
    
    if saved and match_score >= auto_approve_threshold:
        # High confidence match - auto-use saved justification
        justification = saved.justification
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                f"📋 *Auto-using saved justification for {receipt_data.vendor}* ({match_score}% match):\n"
                f"_{saved.justification}_"
            )
        )
    elif saved:
        # Lower confidence - offer saved justification but ask for confirmation
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                f"📋 *Found saved justification for {receipt_data.vendor}* ({match_score}% match):\n"
                f"_{saved.justification}_\n\n"
                "Reply `use` to use this, or type a new justification:"
            )
        )
        
        justification_response, last_seen_ts = await wait_for_reply(
            client, channel, thread_ts, last_seen_ts, timeout=300
        )
        
        if justification_response and justification_response.strip().lower() == "use":
            justification = saved.justification
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"✅ Using saved justification."
            )
        elif justification_response:
            justification = justification_response
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"✅ Justification recorded: _{justification[:100]}{'...' if len(justification) > 100 else ''}_"
            )
        else:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="⏰ No response received. Using saved justification."
            )
            justification = saved.justification
    else:
        # Ask for justification
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="📝 *Please reply with a brief justification for this purchase:*"
        )
        
        justification_response, last_seen_ts = await wait_for_reply(
            client, channel, thread_ts, last_seen_ts, timeout=300
        )
        
        if not justification_response:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="⏰ No justification received. Processing paused."
            )
            return
        
        justification = justification_response
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"✅ Justification recorded: _{justification[:100]}{'...' if len(justification) > 100 else ''}_"
        )
    
    # Step 3: If food, ask for attendee count
    attendee_count = None
    attendee_names = None
    
    if receipt_data and receipt_data.is_food:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="🍕 *Food Purchase Detected!*\n\nHow many people consumed this food?\nPlease reply with just a number (e.g., `3` or `15`)."
        )
        
        count_response, last_seen_ts = await wait_for_reply(
            client, channel, thread_ts, last_seen_ts, timeout=120
        )
        
        if count_response:
            try:
                attendee_count = int(count_response.strip())
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"✅ Got it - {attendee_count} attendees."
                )
                
                # Step 4: If 5 or fewer, ask for names
                if attendee_count <= 5:
                    await client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=f"Since there are {attendee_count} or fewer attendees, I need their names.\n\nPlease reply with all names separated by commas.\nExample: `John Smith, Jane Doe, Bob Wilson`"
                    )
                    
                    names_response, last_seen_ts = await wait_for_reply(
                        client, channel, thread_ts, last_seen_ts, timeout=120
                    )
                    
                    if names_response:
                        attendee_names = names_response
                        await client.chat_postMessage(
                            channel=channel,
                            thread_ts=thread_ts,
                            text=f"✅ Names recorded: {attendee_names}"
                        )
                    else:
                        await client.chat_postMessage(
                            channel=channel,
                            thread_ts=thread_ts,
                            text="⏰ No names received. You may need to fill this in manually."
                        )
            except ValueError:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"⚠️ Couldn't parse '{count_response}' as a number. Proceeding without attendee info."
                )
        else:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="⏰ No response received. Proceeding without attendee info."
            )
    
    # Step 5: Start TPR automation
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="🔄 Starting TPR form automation..."
    )
    
    # Import here to avoid circular imports
    from services.tpr_automation import create_tpr_request, TPRFormAutomation
    from services.google_drive import upload_receipt_to_drive
    from services.google_sheets import update_budget, update_tpr_tracking
    from models.receipt import Purchase
    from utils.helpers import generate_receipt_filename
    
    try:
        # Create TPR request
        tpr_request = await create_tpr_request(
            receipt=receipt_data,
            justification=justification,
            department=None,
            attendee_count=attendee_count,
            attendee_names=attendee_names
        )
        
        # Run TPR automation
        async def notify_callback(msg):
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=msg
            )
        
        tpr_automation = TPRFormAutomation(headless=False)
        tpr_automation.set_notify_callback(notify_callback)
        
        # Use global demo mode flag
        demo_mode = _demo_mode
        
        tpr_number = await tpr_automation.process_tpr(tpr_request, demo_mode=demo_mode)
        
        if tpr_number:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=f"✅ TPR created: `{tpr_number}`"
            )
            
            # Upload to Google Drive
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="☁️ Uploading receipt to Google Drive..."
            )
            
            receipt_filename = generate_receipt_filename(
                receipt_data.vendor,
                receipt_data.formatted_date,
                receipt_data.amount,
                department=receipt_data.category or "Misc"
            )
            receipt_link = await upload_receipt_to_drive(pdf_path, receipt_filename)
            
            # Update spreadsheets
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="📊 Updating budget spreadsheet..."
            )
            
            purchase = Purchase(
                description=f"{receipt_data.vendor} - {justification[:50]}",
                amount=receipt_data.amount,
                vendor=receipt_data.vendor,
                receipt_link=receipt_link,
                tpr_number=tpr_number,
                department=None,
                date=receipt_data.date,
                justification=justification
            )
            
            await update_budget(purchase)
            await update_tpr_tracking(purchase)
            
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f"🎉 *All Done!*\n\n"
                    f"• TPR Number: `{tpr_number}`\n"
                    f"• Receipt uploaded: <{receipt_link}|View in Drive>\n"
                    f"• Budget sheet: ✅ Updated\n"
                    f"• TPR Tracking: ✅ Updated"
                )
            )
            
            # Ask if this is a recurring purchase (only if not using a saved one)
            if not saved:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=(
                        "🔄 Is this a *recurring purchase* (e.g., monthly subscription)?\n"
                        "Reply `yes` to save this justification for future purchases from this vendor, "
                        "or `no` to continue."
                    )
                )
                
                recurring_response, _ = await wait_for_reply(
                    client, channel, thread_ts, last_seen_ts, timeout=60
                )
                
                if recurring_response and recurring_response.strip().lower() in ["yes", "y"]:
                    save_justification(
                        vendor=receipt_data.vendor,
                        justification=justification,
                        category=receipt_data.category or "Misc"
                    )
                    await client.chat_postMessage(
                        channel=channel,
                        thread_ts=thread_ts,
                        text=(
                            f"✅ Saved! Future purchases from *{receipt_data.vendor}* will suggest:\n"
                            f"_{justification}_"
                        )
                    )
        else:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="⚠️ TPR automation completed but could not confirm TPR number."
            )
            
    except Exception as e:
        logger.exception("Error in TPR automation")
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"❌ Error during processing: {str(e)}"
        )


@app.post("/webhook/mailgun")
async def receive_email(
    request: Request,
    sender: str = Form(...),
    subject: str = Form(""),
    timestamp: str = Form(""),
    token: str = Form(""),
    signature: str = Form(""),
    stripped_html: str = Form(default=""),
    stripped_text: str = Form(default=""),
    body_html: str = Form(default="", alias="body-html"),
    body_plain: str = Form(default="", alias="body-plain"),
):
    """Webhook endpoint for Mailgun inbound emails."""
    # Verify signature
    if MailgunConfig.WEBHOOK_SECRET:
        if not verify_mailgun_signature(token, timestamp, signature, MailgunConfig.WEBHOOK_SECRET):
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    logger.info(f"Received email from {sender}: {subject}")
    
    # Get form data for attachments
    form = await request.form()
    
    # Look for PDF attachments
    pdf_path = None
    
    for key in form.keys():
        if key.startswith("attachment"):
            file = form[key]
            if hasattr(file, 'filename') and hasattr(file, 'read'):
                filename = file.filename.lower()
                if filename.endswith('.pdf'):
                    content = await file.read()
                    pdf_path = TEMP_DIR / f"email_receipt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    pdf_path.write_bytes(content)
                    logger.info(f"Saved PDF attachment: {pdf_path}")
                    break
    
    # If no PDF attachment, convert email to PDF
    if not pdf_path:
        logger.info("No PDF attachment found, converting email to PDF")
        html_content = stripped_html or body_html or ""
        plain_content = stripped_text or body_plain or ""
        
        pdf_path = email_to_pdf(
            subject=subject,
            sender=sender,
            date=datetime.now().strftime("%Y-%m-%d %H:%M"),
            body_html=html_content,
            body_plain=plain_content,
            output_path=TEMP_DIR / f"email_receipt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
    
    # Process receipt with VLM
    try:
        receipt_data = extract_receipt_data(pdf_path)
        logger.info(f"Extracted receipt: {receipt_data.vendor} - ${receipt_data.amount}")
    except Exception as e:
        logger.error(f"Failed to process receipt: {e}")
        receipt_data = None
    
    # Start async processing (don't block the webhook response)
    asyncio.create_task(process_email_receipt(
        sender=sender,
        subject=subject,
        receipt_data=receipt_data,
        pdf_path=pdf_path
    ))
    
    return JSONResponse(content={"status": "ok", "message": "Email received and processing started"})


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


def run_webhook_server():
    """Run the webhook server."""
    port = MailgunConfig.WEBHOOK_PORT
    logger.info(f"Starting webhook server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)


async def run_webhook_server_async():
    """Run the webhook server asynchronously."""
    port = MailgunConfig.WEBHOOK_PORT
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
