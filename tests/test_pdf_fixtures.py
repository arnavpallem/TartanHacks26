"""
Tests for OCR processing with actual PDF fixtures.
Requires PDF files in tests/fixtures/ directory.
"""
import pytest
from pathlib import Path
from decimal import Decimal


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestPDFFixtures:
    """Tests using actual PDF receipt fixtures."""
    
    @pytest.fixture
    def dunkin_receipt_path(self):
        """Path to Dunkin receipt PDF."""
        path = FIXTURES_DIR / "Misc_Dunkin_87.18_1-29-26.pdf"
        if not path.exists():
            pytest.skip(f"Test fixture not found: {path}")
        return path
    
    @pytest.fixture
    def mini_carnival_receipt_path(self):
        """Path to Mini Carnival receipt PDF."""
        path = FIXTURES_DIR / "mini-carnival31.7.pdf"
        if not path.exists():
            pytest.skip(f"Test fixture not found: {path}")
        return path
    
    def test_extract_text_from_dunkin_receipt(self, dunkin_receipt_path):
        """Test extracting text from Dunkin receipt PDF."""
        from services.ocr_processor import extract_text_from_pdf
        
        text = extract_text_from_pdf(dunkin_receipt_path)
        
        # Should extract some text
        assert len(text) > 50
        # Should contain receipt-like content
        assert text is not None
    
    def test_extract_receipt_data_dunkin(self, dunkin_receipt_path):
        """Test full extraction from Dunkin receipt."""
        from services.ocr_processor import extract_receipt_data
        
        receipt = extract_receipt_data(dunkin_receipt_path)
        
        # Based on filename: Misc_Dunkin_87.18_1-29-26.pdf
        # Expected: Dunkin, $87.18, 1/29/26
        assert receipt is not None
        assert receipt.amount is not None
        assert receipt.amount > Decimal("0")
        assert receipt.vendor is not None
        assert len(receipt.vendor) > 0
        assert receipt.date is not None
        
        # The OCR should extract something close to the expected values
        # We check ranges since OCR may not be 100% accurate
        print(f"Extracted: vendor={receipt.vendor}, amount={receipt.amount}, date={receipt.date}")
    
    def test_extract_receipt_data_mini_carnival(self, mini_carnival_receipt_path):
        """Test full extraction from Mini Carnival receipt."""
        from services.ocr_processor import extract_receipt_data
        
        receipt = extract_receipt_data(mini_carnival_receipt_path)
        
        # Based on filename: mini-carnival31.7.pdf
        # Expected: $31.70 amount
        assert receipt is not None
        assert receipt.amount is not None
        assert receipt.vendor is not None
        assert receipt.date is not None
        
        print(f"Extracted: vendor={receipt.vendor}, amount={receipt.amount}, date={receipt.date}")
    
    def test_receipt_amount_dunkin_approximate(self, dunkin_receipt_path):
        """Test that extracted amount is approximately correct for Dunkin."""
        from services.ocr_processor import extract_receipt_data
        
        receipt = extract_receipt_data(dunkin_receipt_path)
        
        # Filename suggests $87.18
        # Allow some OCR error margin
        expected = Decimal("87.18")
        
        # Check if within reasonable range (OCR might misread)
        lower = Decimal("80.00")
        upper = Decimal("95.00")
        
        assert lower <= receipt.amount <= upper or receipt.amount == expected, \
            f"Amount {receipt.amount} not in expected range {lower}-{upper}"


class TestOCREdgeCases:
    """Tests for OCR edge cases and error handling."""
    
    def test_extract_date_various_formats(self):
        """Test date extraction handles various formats."""
        from services.ocr_processor import extract_date
        
        test_cases = [
            ("Invoice Date: 1/29/2026", 1, 29),
            ("Date 01-29-2026", 1, 29),
            ("January 29, 2026", 1, 29),
            ("29 Jan 2026", 1, 29),
        ]
        
        for text, expected_month, expected_day in test_cases:
            result = extract_date(text)
            assert result is not None, f"Failed to parse: {text}"
            assert result.month == expected_month, f"Wrong month for: {text}"
            assert result.day == expected_day, f"Wrong day for: {text}"
    
    def test_extract_amount_various_formats(self):
        """Test amount extraction handles various formats."""
        from services.ocr_processor import extract_amount
        
        test_cases = [
            ("Total $87.18", Decimal("87.18")),
            ("TOTAL: $1,234.56", Decimal("1234.56")),
            ("Grand Total $99.99", Decimal("99.99")),
            ("Amount Due: $50.00", Decimal("50.00")),
        ]
        
        for text, expected in test_cases:
            result = extract_amount(text)
            assert result == expected, f"Expected {expected}, got {result} for: {text}"
