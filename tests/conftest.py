"""
Shared test fixtures and configuration.
"""
import pytest
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_receipt_text():
    """Sample OCR text from a receipt."""
    return """
    COSTCO WHOLESALE
    123 Main Street
    Pittsburgh, PA 15213
    
    Date: 01/15/2026
    
    ITEM 1                    $45.99
    ITEM 2                    $23.50
    ITEM 3                    $12.00
    
    Subtotal                  $81.49
    Tax                        $6.52
    ---------------------------------
    TOTAL                     $88.01
    
    Thank you for shopping!
    """


@pytest.fixture
def sample_receipt_amazon():
    """Sample Amazon receipt text."""
    return """
    Amazon.com
    
    Order Confirmation
    February 3, 2026
    
    Office Supplies Bundle
    Qty: 1
    Price: $34.99
    
    Shipping: FREE
    Tax: $2.80
    
    Order Total: $37.79
    
    Ship to: Spring Carnival Committee
    """


@pytest.fixture
def sample_receipt_data():
    """Sample ReceiptData object."""
    from models.receipt import ReceiptData
    return ReceiptData(
        vendor="Costco Wholesale",
        date=datetime(2026, 1, 15),
        amount=Decimal("88.01"),
        raw_text="Sample receipt text",
        file_path=Path("/tmp/sample_receipt.pdf")
    )


@pytest.fixture
def sample_tpr_request(sample_receipt_data):
    """Sample TPRRequest object."""
    from models.receipt import TPRRequest
    return TPRRequest(
        receipt=sample_receipt_data,
        justification="Office supplies for booth construction",
        what_purchased="Supplies",
        department="Booth",
        is_travel=False,
        is_food=False
    )


@pytest.fixture
def sample_purchase():
    """Sample Purchase object."""
    from models.receipt import Purchase
    return Purchase(
        description="Costco - Office supplies for booth",
        amount=Decimal("88.01"),
        receipt_link="https://drive.google.com/file/d/abc123",
        tpr_number="TPR039999",
        department="Booth"
    )


@pytest.fixture
def sample_slack_event():
    """Sample Slack app_mention event."""
    return {
        "type": "app_mention",
        "user": "U123456",
        "channel": "C789012",
        "text": "<@UBOT123> Office supplies for booth construction",
        "ts": "1234567890.123456",
        "files": [
            {
                "id": "F123456",
                "name": "receipt.pdf",
                "mimetype": "application/pdf",
                "url_private": "https://files.slack.com/files-pri/T123/receipt.pdf"
            }
        ]
    }


@pytest.fixture
def sample_slack_event_with_department():
    """Sample Slack event with department specified."""
    return {
        "type": "app_mention",
        "user": "U123456",
        "channel": "C789012",
        "text": "<@UBOT123> Paint for decorations | Department: Booth",
        "ts": "1234567890.123456",
        "files": [
            {
                "id": "F123456",
                "name": "receipt.pdf",
                "mimetype": "application/pdf",
                "url_private": "https://files.slack.com/files-pri/T123/receipt.pdf"
            }
        ]
    }
