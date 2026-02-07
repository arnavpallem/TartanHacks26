"""
Tests for TPR form automation.
Tests form field mapping and navigation without actually submitting.
"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


class TestTPRFieldIDs:
    """Tests to verify field IDs are correctly defined."""
    
    def test_field_ids_all_present(self):
        """Test all required field IDs are defined."""
        from services.tpr_automation import FIELD_IDS
        
        required_fields = [
            # Page 1
            "andrew_id_lookup",
            "on_behalf_of_someone_else",
            "transaction_type",
            "student_org_business",
            "organization_name",
            "organization_name_other",
            "account_charged",
            "amount_page1",
            "travel_expenses",
            # Page 2
            "who_field",
            "what_purchased",
            "when_field",
            "where_field",
            "why_field",
            "printing_services",
            # Page 3
            "vendor_name",
            "receipt_description",
            "receipt_date",
            "receipt_total",
            "received_goods",
            "gift_or_prize",
            "add_another_receipt",
        ]
        
        for field in required_fields:
            assert field in FIELD_IDS, f"Missing field ID: {field}"
            assert len(FIELD_IDS[field]) > 10, f"Field ID looks invalid: {field}"
    
    def test_navigation_selectors_defined(self):
        """Test navigation selectors are defined."""
        from services.tpr_automation import NAV_NEXT, NAV_PREV, NAV_SUBMIT
        
        assert "button" in NAV_NEXT.lower() or "primary" in NAV_NEXT.lower()
        assert "button" in NAV_PREV.lower() or "secondary" in NAV_PREV.lower()
        assert NAV_SUBMIT is not None
    
    def test_login_selectors_defined(self):
        """Test login selectors are defined."""
        from services.tpr_automation import LOGIN_USERNAME, LOGIN_PASSWORD
        
        assert "username" in LOGIN_USERNAME
        assert "password" in LOGIN_PASSWORD


class TestTPRFormAutomation:
    """Tests for TPRFormAutomation class."""
    
    def test_init_default_headless(self):
        """Test default headless mode is False."""
        from services.tpr_automation import TPRFormAutomation
        
        automation = TPRFormAutomation()
        assert automation.headless is False
    
    def test_init_custom_headless(self):
        """Test custom headless mode."""
        from services.tpr_automation import TPRFormAutomation
        
        automation = TPRFormAutomation(headless=True)
        assert automation.headless is True
    
    def test_set_notify_callback(self):
        """Test setting notification callback."""
        from services.tpr_automation import TPRFormAutomation
        
        automation = TPRFormAutomation()
        callback = AsyncMock()
        automation.set_notify_callback(callback)
        
        assert automation._notify_callback == callback
    
    @pytest.mark.asyncio
    async def test_notify_with_callback(self):
        """Test notification is sent via callback."""
        from services.tpr_automation import TPRFormAutomation
        
        automation = TPRFormAutomation()
        callback = AsyncMock()
        automation.set_notify_callback(callback)
        
        await automation._notify("Test message")
        
        callback.assert_called_once_with("Test message")
    
    @pytest.mark.asyncio
    async def test_notify_without_callback(self):
        """Test notification works without callback (just logs)."""
        from services.tpr_automation import TPRFormAutomation
        
        automation = TPRFormAutomation()
        # Should not raise
        await automation._notify("Test message")


class TestCreateTPRRequest:
    """Tests for create_tpr_request function."""
    
    @pytest.mark.asyncio
    async def test_create_tpr_request(self, sample_receipt_data):
        """Test creating a TPR request from receipt data."""
        from services.tpr_automation import create_tpr_request
        
        justification = "Office supplies for booth construction"
        
        tpr_request = await create_tpr_request(
            receipt=sample_receipt_data,
            justification=justification,
            department="Booth"
        )
        
        assert tpr_request.receipt == sample_receipt_data
        assert tpr_request.justification == justification
        assert tpr_request.department == "Booth"
        assert tpr_request.what_purchased == "Office"  # First word extracted
        assert tpr_request.is_travel is False
        assert tpr_request.is_food is False
    
    @pytest.mark.asyncio
    async def test_create_tpr_request_extracts_descriptor(self, sample_receipt_data):
        """Test that one-word descriptor is extracted from justification."""
        from services.tpr_automation import create_tpr_request
        
        tpr_request = await create_tpr_request(
            receipt=sample_receipt_data,
            justification="Paint for decorations"
        )
        
        assert tpr_request.what_purchased == "Paint"


class TestTPRNumberExtraction:
    """Tests for TPR number extraction from confirmation pages."""
    
    @pytest.mark.asyncio
    async def test_extract_tpr_number_pattern1(self):
        """Test extracting TPR number from 'TPR #123456' pattern."""
        from services.tpr_automation import TPRFormAutomation
        
        automation = TPRFormAutomation()
        automation.page = MagicMock()
        automation.page.content = AsyncMock(return_value="Your TPR #123456 has been submitted")
        
        result = await automation._extract_tpr_number()
        
        assert result == "TPR123456"
    
    @pytest.mark.asyncio
    async def test_extract_tpr_number_pattern2(self):
        """Test extracting TPR number from 'Reference: 789012' pattern."""
        from services.tpr_automation import TPRFormAutomation
        
        automation = TPRFormAutomation()
        automation.page = MagicMock()
        automation.page.content = AsyncMock(return_value="Reference #: 789012 - Submitted")
        
        result = await automation._extract_tpr_number()
        
        assert result == "TPR789012"
    
    @pytest.mark.asyncio
    async def test_extract_tpr_number_unknown(self):
        """Test fallback when no TPR number found."""
        from services.tpr_automation import TPRFormAutomation
        
        automation = TPRFormAutomation()
        automation.page = MagicMock()
        automation.page.content = AsyncMock(return_value="Form submitted successfully")
        
        result = await automation._extract_tpr_number()
        
        assert result == "TPR-UNKNOWN"
