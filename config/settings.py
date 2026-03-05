"""
Configuration settings loaded from environment variables.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"
TEMP_DIR = PROJECT_ROOT / "temp"

# Ensure directories exist
CREDENTIALS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)


class SlackConfig:
    """Slack API configuration."""
    BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
    APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
    SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")


class CMUConfig:
    """CMU authentication configuration."""
    ANDREW_ID = os.getenv("CMU_ANDREW_ID", "")
    PASSWORD = os.getenv("CMU_PASSWORD", "")
    TPR_FORM_URL = "https://xforms.andrew.cmu.edu/SATransactionProcessingRequest"


class GoogleConfig:
    """Google API configuration."""
    CREDENTIALS_PATH = os.getenv(
        "GOOGLE_CREDENTIALS_PATH",
        str(CREDENTIALS_DIR / "google_credentials.json")
    )
    TOKEN_PATH = str(CREDENTIALS_DIR / "token.json")
    
    # API Scopes
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ]


class GeminiConfig:
    """Google Gemini VLM configuration for receipt processing."""
    API_KEY = os.getenv("GEMINI_API_KEY", "")
    MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")


class OllamaConfig:
    """Ollama local VLM configuration for receipt processing."""
    URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
    MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-vl:7b")
    TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))  # seconds, CPU inference is slow
    ENABLED = os.getenv("OLLAMA_ENABLED", "true").lower() in ("true", "1", "yes")


# Database
DATABASE_URL = os.getenv("DATABASE_URL", "")


class MailgunConfig:
    """Mailgun inbound email configuration."""
    API_KEY = os.getenv("MAILGUN_API_KEY", "")
    WEBHOOK_SECRET = os.getenv("MAILGUN_WEBHOOK_SECRET", "")
    # Slack channel to post email receipts to
    NOTIFY_CHANNEL = os.getenv("MAILGUN_NOTIFY_CHANNEL", "")
    # Webhook port for FastAPI server
    WEBHOOK_PORT = int(os.getenv("MAILGUN_WEBHOOK_PORT", "8000"))


class FilePathConfig:
    """Google Drive/Sheets file paths."""
    # Note: Folder 'Receipts/Invoices' contains a slash in its name
    # We use '|' as delimiter for folder names that contain slashes
    RECEIPTS_FOLDER = os.getenv(
        "RECEIPTS_FOLDER_PATH",
        "Spring Carnival 2026|Finance|Receipts/Invoices"
    )
    BUDGET_SPREADSHEET = os.getenv(
        "BUDGET_SPREADSHEET_PATH",
        "Spring Carnival 2026|Finance|FY2026 Budget"
    )
    TPR_TRACKING_SHEET = os.getenv(
        "TPR_TRACKING_SHEET_PATH",
        "Spring Carnival 2026|Finance|TPR Tracking Sheet"
    )


def validate_config() -> list[str]:
    """
    Validate that all required configuration is present.
    Returns a list of missing configuration items.
    """
    missing = []
    
    if not SlackConfig.BOT_TOKEN:
        missing.append("SLACK_BOT_TOKEN")
    if not SlackConfig.APP_TOKEN:
        missing.append("SLACK_APP_TOKEN")
    if not CMUConfig.ANDREW_ID:
        missing.append("CMU_ANDREW_ID")
    if not CMUConfig.PASSWORD:
        missing.append("CMU_PASSWORD")
    if not Path(GoogleConfig.CREDENTIALS_PATH).exists():
        missing.append(f"Google credentials file at {GoogleConfig.CREDENTIALS_PATH}")
    
    return missing
