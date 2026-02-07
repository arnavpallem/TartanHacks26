"""
Data models for receipt processing and TPR requests.
"""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional
from pathlib import Path


@dataclass
class ReceiptData:
    """Extracted data from a receipt."""
    vendor: str
    date: datetime
    amount: Decimal
    raw_text: str = ""
    file_path: Optional[Path] = None
    # VLM-extracted fields
    category: Optional[str] = None  # Budget category: Misc, Operations, Electrical, Booth, Entertainment
    short_description: Optional[str] = None  # 2-4 word description
    is_food: bool = False  # For TPR form
    is_travel: bool = False  # For TPR form
    
    @property
    def formatted_date(self) -> str:
        """Return date in MM/DD/YYYY format for TPR form."""
        return self.date.strftime("%m/%d/%Y")
    
    @property
    def formatted_amount(self) -> str:
        """Return amount in xxx.xx format for TPR form."""
        return f"{self.amount:.2f}"


@dataclass
class TPRRequest:
    """A complete TPR request with all required information."""
    receipt: ReceiptData
    justification: str
    what_purchased: str  # One-word descriptor
    department: Optional[str] = None
    is_travel: bool = False
    is_food: bool = False
    attendee_count: Optional[int] = None
    tpr_number: Optional[str] = None
    
    @property
    def who_field(self) -> str:
        """Format for the 'Who' field: First initial + Last name."""
        from config.constants import PREPARER_WHO_FORMAT
        return PREPARER_WHO_FORMAT


@dataclass
class Purchase:
    """A processed purchase ready for spreadsheet entry."""
    description: str
    amount: Decimal
    receipt_link: str = ""
    tpr_number: str = ""
    department: Optional[str] = None
    date: Optional[datetime] = None
    
    @property
    def amount_negative(self) -> str:
        """Return amount as negative value for budget 'Actual' column."""
        return f"-{self.amount:.2f}"


@dataclass
class SlackMessage:
    """Parsed Slack message with receipt request."""
    user_id: str
    channel_id: str
    file_url: str
    file_name: str
    justification: str
    department: Optional[str] = None
    thread_ts: Optional[str] = None
    
    @classmethod
    def parse_message(cls, text: str, file_info: dict, event: dict) -> "SlackMessage":
        """
        Parse a Slack message to extract justification and optional department.
        
        Format: "justification text | Department: DeptName"
        """
        department = None
        justification = text.strip()
        
        # Check for department specification
        if "|" in text:
            parts = text.split("|")
            justification = parts[0].strip()
            for part in parts[1:]:
                if "department:" in part.lower():
                    department = part.split(":", 1)[1].strip()
        
        # Remove bot mention from justification
        justification = " ".join(
            word for word in justification.split() 
            if not word.startswith("<@")
        ).strip()
        
        return cls(
            user_id=event.get("user", ""),
            channel_id=event.get("channel", ""),
            file_url=file_info.get("url_private", ""),
            file_name=file_info.get("name", "receipt.pdf"),
            justification=justification,
            department=department,
            thread_ts=event.get("ts"),
        )
