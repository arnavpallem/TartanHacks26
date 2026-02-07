"""
Gmail monitoring service for detecting incoming receipts.
Runs daily to check for new receipt emails.
"""
import asyncio
import base64
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from config.settings import GoogleConfig, TEMP_DIR
from config.constants import RECEIPT_KEYWORDS, RECEIPT_SENDERS, GMAIL_CHECK_INTERVAL_HOURS

logger = logging.getLogger(__name__)


class GmailMonitorService:
    """Service for monitoring Gmail for incoming receipts."""
    
    def __init__(self):
        self.creds: Optional[Credentials] = None
        self.service = None
        self._last_check: Optional[datetime] = None
        self._notify_callback = None
    
    def set_notify_callback(self, callback):
        """Set callback for Slack notifications."""
        self._notify_callback = callback
    
    def authenticate(self):
        """Authenticate with Gmail API using OAuth."""
        creds = None
        token_path = Path(GoogleConfig.TOKEN_PATH)
        
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(token_path), GoogleConfig.SCOPES
            )
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    GoogleConfig.CREDENTIALS_PATH, GoogleConfig.SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            token_path.write_text(creds.to_json())
        
        self.creds = creds
        self.service = build('gmail', 'v1', credentials=creds)
        logger.info("Gmail authenticated successfully")
    
    def _build_search_query(self, since_date: datetime = None) -> str:
        """Build Gmail search query for receipts."""
        query_parts = []
        
        # Time filter
        if since_date:
            date_str = since_date.strftime("%Y/%m/%d")
            query_parts.append(f"after:{date_str}")
        else:
            # Default to last 24 hours
            yesterday = datetime.now() - timedelta(hours=24)
            query_parts.append(f"after:{yesterday.strftime('%Y/%m/%d')}")
        
        # Has attachment
        query_parts.append("has:attachment")
        
        # Keyword filter (in subject or body)
        keyword_filter = " OR ".join([f'("{kw}")' for kw in RECEIPT_KEYWORDS])
        query_parts.append(f"({keyword_filter})")
        
        return " ".join(query_parts)
    
    def search_receipt_emails(self, since_date: datetime = None) -> List[dict]:
        """
        Search for emails that might contain receipts.
        
        Returns:
            List of email metadata dicts
        """
        if not self.service:
            self.authenticate()
        
        query = self._build_search_query(since_date)
        logger.info(f"Searching Gmail with query: {query}")
        
        results = self.service.users().messages().list(
            userId='me',
            q=query,
            maxResults=20
        ).execute()
        
        messages = results.get('messages', [])
        
        receipt_emails = []
        for msg in messages:
            email_data = self._get_email_details(msg['id'])
            if email_data and self._is_likely_receipt(email_data):
                receipt_emails.append(email_data)
        
        logger.info(f"Found {len(receipt_emails)} potential receipt emails")
        return receipt_emails
    
    def _get_email_details(self, message_id: str) -> Optional[dict]:
        """Get detailed information about an email."""
        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            headers = {h['name'].lower(): h['value'] for h in message['payload'].get('headers', [])}
            
            return {
                'id': message_id,
                'subject': headers.get('subject', ''),
                'from': headers.get('from', ''),
                'date': headers.get('date', ''),
                'snippet': message.get('snippet', ''),
                'has_pdf': self._has_pdf_attachment(message['payload']),
                'attachments': self._get_attachment_info(message['payload'])
            }
        except Exception as e:
            logger.error(f"Error getting email details: {e}")
            return None
    
    def _has_pdf_attachment(self, payload: dict) -> bool:
        """Check if email has a PDF attachment."""
        parts = payload.get('parts', [])
        for part in parts:
            if part.get('mimeType') == 'application/pdf':
                return True
            if part.get('filename', '').endswith('.pdf'):
                return True
            # Check nested parts
            if 'parts' in part:
                if self._has_pdf_attachment(part):
                    return True
        return False
    
    def _get_attachment_info(self, payload: dict) -> List[dict]:
        """Get information about all attachments."""
        attachments = []
        parts = payload.get('parts', [])
        
        for part in parts:
            filename = part.get('filename', '')
            if filename and part.get('body', {}).get('attachmentId'):
                attachments.append({
                    'filename': filename,
                    'mimeType': part.get('mimeType', ''),
                    'attachmentId': part['body']['attachmentId']
                })
            # Check nested parts
            if 'parts' in part:
                attachments.extend(self._get_attachment_info(part))
        
        return attachments
    
    def _is_likely_receipt(self, email_data: dict) -> bool:
        """Determine if an email is likely to contain a receipt."""
        subject = email_data.get('subject', '').lower()
        sender = email_data.get('from', '').lower()
        snippet = email_data.get('snippet', '').lower()
        
        # Check for receipt keywords in subject
        for keyword in RECEIPT_KEYWORDS:
            if keyword.lower() in subject:
                return True
        
        # Check for known receipt senders
        for known_sender in RECEIPT_SENDERS:
            if known_sender.lower() in sender:
                return True
        
        # Check snippet for keywords
        for keyword in RECEIPT_KEYWORDS:
            if keyword.lower() in snippet:
                return True
        
        # Must have PDF if no keyword matches
        return email_data.get('has_pdf', False)
    
    def download_attachment(self, message_id: str, attachment_id: str, filename: str) -> Path:
        """Download an email attachment."""
        attachment = self.service.users().messages().attachments().get(
            userId='me',
            messageId=message_id,
            id=attachment_id
        ).execute()
        
        data = base64.urlsafe_b64decode(attachment['data'])
        
        file_path = TEMP_DIR / filename
        file_path.write_bytes(data)
        
        logger.info(f"Downloaded attachment: {filename}")
        return file_path
    
    async def check_for_receipts(self) -> List[dict]:
        """
        Check for new receipt emails since last check.
        
        Returns:
            List of new receipt email data
        """
        since_date = self._last_check or (datetime.now() - timedelta(hours=GMAIL_CHECK_INTERVAL_HOURS))
        
        receipts = self.search_receipt_emails(since_date)
        self._last_check = datetime.now()
        
        return receipts
    
    async def notify_user_of_receipts(self, receipts: List[dict], slack_channel: str, slack_client):
        """Send Slack notifications for detected receipts."""
        for receipt in receipts:
            subject = receipt.get('subject', 'No subject')
            sender = receipt.get('from', 'Unknown sender')
            date = receipt.get('date', '')
            
            message = (
                f"📧 **New Receipt Detected!**\n\n"
                f"• From: {sender}\n"
                f"• Subject: {subject}\n"
                f"• Date: {date}\n\n"
                f"Would you like me to process this receipt and fill out a TPR?\n"
                f"Reply with: `process <email_id>` and your justification\n"
                f"Email ID: `{receipt.get('id')}`"
            )
            
            await slack_client.chat_postMessage(
                channel=slack_channel,
                text=message
            )


# Global instance
_gmail_service: Optional[GmailMonitorService] = None


def get_gmail_service() -> GmailMonitorService:
    """Get the global Gmail service instance."""
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = GmailMonitorService()
        _gmail_service.authenticate()
    return _gmail_service


async def run_daily_gmail_check(slack_channel: str, slack_client):
    """Run the daily Gmail check for receipts."""
    service = get_gmail_service()
    receipts = await service.check_for_receipts()
    
    if receipts:
        await service.notify_user_of_receipts(receipts, slack_channel, slack_client)
        logger.info(f"Notified user of {len(receipts)} new receipts")
    else:
        logger.info("No new receipts found")
