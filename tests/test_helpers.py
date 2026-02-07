"""
Tests for helper utilities - department matching, text processing.
"""
import pytest
from decimal import Decimal


class TestExtractOneWordDescriptor:
    """Tests for one-word descriptor extraction."""
    
    def test_extract_descriptor_simple(self):
        """Test simple description."""
        from utils.helpers import extract_one_word_descriptor
        
        result = extract_one_word_descriptor("Office supplies for the booth")
        
        assert result == "Office"
    
    def test_extract_descriptor_filters_stop_words(self):
        """Test filtering common stop words."""
        from utils.helpers import extract_one_word_descriptor
        
        result = extract_one_word_descriptor("the paint for decorations")
        
        assert result == "Paint"
    
    def test_extract_descriptor_filters_org_words(self):
        """Test filtering organization-specific words."""
        from utils.helpers import extract_one_word_descriptor
        
        result = extract_one_word_descriptor("Spring Carnival Committee supplies")
        
        assert result == "Supplies"
    
    def test_extract_descriptor_fallback(self):
        """Test fallback to 'Supplies' when no meaningful words."""
        from utils.helpers import extract_one_word_descriptor
        
        result = extract_one_word_descriptor("the a an")
        
        assert result == "Supplies"


class TestMatchDepartment:
    """Tests for department matching."""
    
    def test_match_explicit_department(self):
        """Test explicit department takes priority."""
        from utils.helpers import match_department
        
        result = match_department("office supplies", "Booth")
        
        assert result == "Booth Line Items"
    
    def test_match_booth_keywords(self):
        """Test matching booth-related keywords."""
        from utils.helpers import match_department
        
        result = match_department("lumber and paint for booth construction")
        
        assert result == "Booth Line Items"
    
    def test_match_electrical_keywords(self):
        """Test matching electrical keywords."""
        from utils.helpers import match_department
        
        result = match_department("extension cords and lights for electrical")
        
        assert result == "Electrical Line Items"
    
    def test_match_entertainment_keywords(self):
        """Test matching entertainment keywords."""
        from utils.helpers import match_department
        
        result = match_department("speakers for music performance")
        
        assert result == "Entertainment Line Items"
    
    def test_match_operations_keywords(self):
        """Test matching operations keywords."""
        from utils.helpers import match_department
        
        result = match_department("logistics equipment and tools")
        
        assert result == "Operations Line Items"
    
    def test_match_misc_keywords(self):
        """Test matching misc keywords."""
        from utils.helpers import match_department
        
        result = match_department("food for GBM meeting")
        
        assert result == "Misc Line Items"
    
    def test_match_default_to_misc(self):
        """Test defaulting to Misc when no match."""
        from utils.helpers import match_department
        
        result = match_department("random unrelated thing xyz")
        
        assert result == "Misc Line Items"


class TestParseAmount:
    """Tests for amount parsing."""
    
    def test_parse_simple_amount(self):
        """Test parsing simple amount."""
        from utils.helpers import parse_amount
        
        result = parse_amount("123.45")
        
        assert result == Decimal("123.45")
    
    def test_parse_amount_with_dollar_sign(self):
        """Test parsing amount with dollar sign."""
        from utils.helpers import parse_amount
        
        result = parse_amount("$99.99")
        
        assert result == Decimal("99.99")
    
    def test_parse_amount_with_comma(self):
        """Test parsing amount with comma."""
        from utils.helpers import parse_amount
        
        result = parse_amount("$1,234.56")
        
        assert result == Decimal("1234.56")
    
    def test_parse_amount_empty(self):
        """Test parsing empty string."""
        from utils.helpers import parse_amount
        
        result = parse_amount("")
        
        assert result is None
    
    def test_parse_amount_invalid(self):
        """Test parsing invalid string."""
        from utils.helpers import parse_amount
        
        result = parse_amount("not a number")
        
        assert result is None


class TestSanitizeFilename:
    """Tests for filename sanitization."""
    
    def test_sanitize_removes_special_chars(self):
        """Test removing special characters."""
        from utils.helpers import sanitize_filename
        
        result = sanitize_filename('file<name>:with/bad\\chars.pdf')
        
        assert '<' not in result
        assert '>' not in result
        assert ':' not in result
        assert '/' not in result
        assert '\\' not in result
    
    def test_sanitize_empty_fallback(self):
        """Test fallback for empty result."""
        from utils.helpers import sanitize_filename
        
        result = sanitize_filename("...")
        
        assert result == "receipt"


class TestGenerateReceiptFilename:
    """Tests for receipt filename generation."""
    
    def test_generate_filename(self):
        """Test generating a receipt filename."""
        from utils.helpers import generate_receipt_filename
        
        result = generate_receipt_filename("Amazon", "01/15/2026", Decimal("45.99"))
        
        assert "Amazon" in result
        assert result.endswith(".pdf")
