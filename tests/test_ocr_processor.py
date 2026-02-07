"""
Tests for OCR processor - date, amount, and vendor extraction.
"""
import pytest
from datetime import datetime
from decimal import Decimal


class TestExtractDate:
    """Tests for date extraction from receipt text."""
    
    def test_extract_date_mm_dd_yyyy(self):
        """Test MM/DD/YYYY format."""
        from services.ocr_processor import extract_date
        
        text = "Date: 01/15/2026\nTotal: $50.00"
        result = extract_date(text)
        
        assert result is not None
        assert result.month == 1
        assert result.day == 15
        assert result.year == 2026
    
    def test_extract_date_month_name(self):
        """Test month name format like 'February 3, 2026'."""
        from services.ocr_processor import extract_date
        
        text = "Order Date: February 3, 2026\nAmount: $100"
        result = extract_date(text)
        
        assert result is not None
        assert result.month == 2
        assert result.day == 3
        assert result.year == 2026
    
    def test_extract_date_with_dashes(self):
        """Test MM-DD-YYYY format."""
        from services.ocr_processor import extract_date
        
        text = "Transaction: 12-25-2025"
        result = extract_date(text)
        
        assert result is not None
        assert result.month == 12
        assert result.day == 25
    
    def test_extract_date_no_date_returns_today(self):
        """Test fallback to today when no date found."""
        from services.ocr_processor import extract_date
        
        text = "Some text without a date"
        result = extract_date(text)
        
        # Should return a date (today as fallback)
        assert result is not None
        assert isinstance(result, datetime)


class TestExtractAmount:
    """Tests for amount extraction from receipt text."""
    
    def test_extract_amount_total(self):
        """Test extracting amount after 'Total' keyword."""
        from services.ocr_processor import extract_amount
        
        text = "Subtotal: $45.00\nTax: $3.60\nTotal: $48.60"
        result = extract_amount(text)
        
        assert result == Decimal("48.60")
    
    def test_extract_amount_grand_total(self):
        """Test extracting grand total."""
        from services.ocr_processor import extract_amount
        
        text = "Grand Total: $125.99"
        result = extract_amount(text)
        
        assert result == Decimal("125.99")
    
    def test_extract_amount_with_comma(self):
        """Test amount with comma separator."""
        from services.ocr_processor import extract_amount
        
        text = "Order Total: $1,234.56"
        result = extract_amount(text)
        
        assert result == Decimal("1234.56")
    
    def test_extract_amount_dollar_sign(self):
        """Test finding largest dollar amount when no 'total' keyword."""
        from services.ocr_processor import extract_amount
        
        text = "Item 1: $10.00\nItem 2: $25.00\n$35.00"
        result = extract_amount(text)
        
        assert result == Decimal("35.00")
    
    def test_extract_amount_none_when_no_amounts(self):
        """Test returns None when no amounts found."""
        from services.ocr_processor import extract_amount
        
        text = "No amounts here"
        result = extract_amount(text)
        
        assert result is None


class TestExtractVendor:
    """Tests for vendor name extraction."""
    
    def test_extract_vendor_first_line(self):
        """Test vendor name from first meaningful line."""
        from services.ocr_processor import extract_vendor
        
        text = "COSTCO WHOLESALE\n123 Main St\nPittsburgh PA"
        result = extract_vendor(text)
        
        assert "COSTCO" in result.upper()
    
    def test_extract_vendor_skip_date(self):
        """Test skipping date lines."""
        from services.ocr_processor import extract_vendor
        
        text = "01/15/2026\nAmazon.com\nOrder #123"
        result = extract_vendor(text)
        
        assert "Amazon" in result or "amazon" in result.lower()
    
    def test_extract_vendor_skip_phone(self):
        """Test skipping phone number lines."""
        from services.ocr_processor import extract_vendor
        
        text = "412-555-1234\nHome Depot\n123 Street"
        result = extract_vendor(text)
        
        assert "Home Depot" in result or "depot" in result.lower()
    
    def test_extract_vendor_unknown_fallback(self):
        """Test fallback when vendor can't be determined."""
        from services.ocr_processor import extract_vendor
        
        text = ""
        result = extract_vendor(text)
        
        assert result == "Unknown Vendor"


class TestFullExtraction:
    """Integration tests for full receipt extraction."""
    
    def test_extract_from_costco_receipt(self, sample_receipt_text):
        """Test extraction from sample Costco receipt."""
        from services.ocr_processor import extract_date, extract_amount, extract_vendor
        
        vendor = extract_vendor(sample_receipt_text)
        date = extract_date(sample_receipt_text)
        amount = extract_amount(sample_receipt_text)
        
        assert "COSTCO" in vendor.upper()
        assert date.month == 1
        assert date.day == 15
        assert amount == Decimal("88.01")
    
    def test_extract_from_amazon_receipt(self, sample_receipt_amazon):
        """Test extraction from sample Amazon receipt."""
        from services.ocr_processor import extract_date, extract_amount, extract_vendor
        
        vendor = extract_vendor(sample_receipt_amazon)
        date = extract_date(sample_receipt_amazon)
        amount = extract_amount(sample_receipt_amazon)
        
        assert "amazon" in vendor.lower()
        assert date.month == 2
        assert amount == Decimal("37.79")
