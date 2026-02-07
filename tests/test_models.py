"""
Tests for data models - ReceiptData, TPRRequest, Purchase, SlackMessage.
"""
import pytest
from datetime import datetime
from decimal import Decimal
from pathlib import Path


class TestReceiptData:
    """Tests for ReceiptData model."""
    
    def test_receipt_data_creation(self):
        """Test creating ReceiptData."""
        from models.receipt import ReceiptData
        
        receipt = ReceiptData(
            vendor="Test Vendor",
            date=datetime(2026, 1, 15),
            amount=Decimal("99.99"),
            raw_text="Sample text"
        )
        
        assert receipt.vendor == "Test Vendor"
        assert receipt.amount == Decimal("99.99")
    
    def test_formatted_date(self):
        """Test formatted_date property."""
        from models.receipt import ReceiptData
        
        receipt = ReceiptData(
            vendor="Test",
            date=datetime(2026, 1, 15),
            amount=Decimal("10.00"),
            raw_text=""
        )
        
        assert receipt.formatted_date == "01/15/2026"
    
    def test_formatted_amount(self):
        """Test formatted_amount property."""
        from models.receipt import ReceiptData
        
        receipt = ReceiptData(
            vendor="Test",
            date=datetime(2026, 1, 1),
            amount=Decimal("1234.50"),
            raw_text=""
        )
        
        assert receipt.formatted_amount == "1234.50"
    
    def test_formatted_amount_pads_decimals(self):
        """Test formatted_amount pads to 2 decimals."""
        from models.receipt import ReceiptData
        
        receipt = ReceiptData(
            vendor="Test",
            date=datetime(2026, 1, 1),
            amount=Decimal("50"),
            raw_text=""
        )
        
        assert receipt.formatted_amount == "50.00"


class TestTPRRequest:
    """Tests for TPRRequest model."""
    
    def test_tpr_request_creation(self, sample_receipt_data):
        """Test creating TPRRequest."""
        from models.receipt import TPRRequest
        
        tpr = TPRRequest(
            receipt=sample_receipt_data,
            justification="Test purchase",
            what_purchased="Supplies"
        )
        
        assert tpr.justification == "Test purchase"
        assert tpr.what_purchased == "Supplies"
        assert tpr.is_travel is False
        assert tpr.is_food is False
    
    def test_who_field_format(self, sample_receipt_data):
        """Test who_field property returns correct format."""
        from models.receipt import TPRRequest
        
        tpr = TPRRequest(
            receipt=sample_receipt_data,
            justification="Test",
            what_purchased="Test"
        )
        
        # Should return "A Pallem" based on constants
        assert tpr.who_field == "A Pallem"


class TestPurchase:
    """Tests for Purchase model."""
    
    def test_purchase_creation(self):
        """Test creating Purchase."""
        from models.receipt import Purchase
        
        purchase = Purchase(
            description="Test purchase",
            amount=Decimal("50.00"),
            receipt_link="https://example.com",
            tpr_number="TPR123456"
        )
        
        assert purchase.description == "Test purchase"
        assert purchase.tpr_number == "TPR123456"
    
    def test_amount_negative(self):
        """Test amount_negative property for budget sheet."""
        from models.receipt import Purchase
        
        purchase = Purchase(
            description="Test",
            amount=Decimal("88.01")
        )
        
        assert purchase.amount_negative == "-88.01"


class TestSlackMessage:
    """Tests for SlackMessage parsing."""
    
    def test_parse_simple_message(self, sample_slack_event):
        """Test parsing simple message without department."""
        from models.receipt import SlackMessage
        
        file_info = sample_slack_event["files"][0]
        text = "Office supplies for booth construction"
        
        result = SlackMessage.parse_message(text, file_info, sample_slack_event)
        
        assert result.justification == "Office supplies for booth construction"
        assert result.department is None
        assert result.user_id == "U123456"
        assert result.channel_id == "C789012"
    
    def test_parse_message_with_department(self, sample_slack_event):
        """Test parsing message with department specified."""
        from models.receipt import SlackMessage
        
        file_info = sample_slack_event["files"][0]
        text = "Paint for decorations | Department: Booth"
        
        result = SlackMessage.parse_message(text, file_info, sample_slack_event)
        
        assert result.justification == "Paint for decorations"
        assert result.department == "Booth"
    
    def test_parse_message_removes_bot_mention(self, sample_slack_event):
        """Test that bot mention is removed from justification."""
        from models.receipt import SlackMessage
        
        file_info = sample_slack_event["files"][0]
        text = "<@UBOT123> Office supplies for booth"
        
        result = SlackMessage.parse_message(text, file_info, sample_slack_event)
        
        assert "<@UBOT123>" not in result.justification
        assert result.justification == "Office supplies for booth"
    
    def test_parse_message_preserves_file_info(self, sample_slack_event):
        """Test that file info is preserved."""
        from models.receipt import SlackMessage
        
        file_info = sample_slack_event["files"][0]
        text = "Test"
        
        result = SlackMessage.parse_message(text, file_info, sample_slack_event)
        
        assert result.file_url == file_info["url_private"]
        assert result.file_name == "receipt.pdf"
