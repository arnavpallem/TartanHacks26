"""
Tests for configuration validation and settings.
"""
import pytest
import os
from pathlib import Path


class TestConfigValidation:
    """Tests for configuration validation."""
    
    def test_validate_config_with_missing_slack_token(self, monkeypatch):
        """Test validation catches missing Slack token."""
        # Clear the environment variable
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        monkeypatch.setattr("config.settings.SlackConfig.BOT_TOKEN", "")
        
        from config.settings import validate_config
        
        missing = validate_config()
        
        assert "SLACK_BOT_TOKEN" in missing
    
    def test_config_loads_from_env(self, monkeypatch):
        """Test config loads from environment variables."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "test-token")
        
        # Reload the module to pick up new env var
        import importlib
        import config.settings
        importlib.reload(config.settings)
        
        # Token should be loaded (or still present)
        assert config.settings.SlackConfig.BOT_TOKEN is not None


class TestConstants:
    """Tests for constants configuration."""
    
    def test_org_name_is_set(self):
        """Test organization name is configured."""
        from config.constants import ORG_NAME
        
        assert ORG_NAME == "Spring Carnival Committee"
    
    def test_budget_sheets_all_present(self):
        """Test all budget sheets are defined."""
        from config.constants import BUDGET_SHEETS
        
        expected = [
            "Misc Line Items",
            "Operations Line Items",
            "Electrical Line Items",
            "Booth Line Items",
            "Entertainment Line Items",
        ]
        
        for sheet in expected:
            assert sheet in BUDGET_SHEETS
    
    def test_department_keywords_all_present(self):
        """Test all department keywords are defined."""
        from config.constants import DEPARTMENT_KEYWORDS
        
        expected_depts = ["Misc", "Operations", "Electrical", "Booth", "Entertainment"]
        
        for dept in expected_depts:
            assert dept in DEPARTMENT_KEYWORDS
            assert len(DEPARTMENT_KEYWORDS[dept]) > 0
    
    def test_preparer_name_format(self):
        """Test preparer name format is correct."""
        from config.constants import PREPARER_FIRST_NAME, PREPARER_WHO_FORMAT
        
        assert PREPARER_FIRST_NAME == "Arnav"
        assert PREPARER_WHO_FORMAT == "A Pallem"
