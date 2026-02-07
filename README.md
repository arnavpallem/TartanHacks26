# Finance Automation Slack Bot

A Slack bot that automates club financial management for Spring Carnival Committee.

## Features

- 📄 **Receipt Processing**: OCR extraction of date, amount, and vendor from PDF receipts
- 📝 **TPR Form Automation**: Automated filling of CMU Transaction Processing Request forms
- ☁️ **Google Drive**: Receipt upload and shareable link generation
- 📊 **Google Sheets**: Budget tracking and TPR logging
- 📧 **Gmail Monitoring**: Daily scan for incoming receipts

## Prerequisites

- Python 3.10+
- Tesseract OCR (`brew install tesseract`)
- Poppler (`brew install poppler`)
- Google Cloud Project with Gmail, Drive, and Sheets APIs enabled
- Slack App with Socket Mode enabled

## Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

## Configuration

1. Copy `.env.example` to `.env` and fill in your credentials
2. Place Google OAuth credentials in `credentials/google_credentials.json`
3. Configure Slack app tokens in `.env`

## Usage

```bash
# Start the bot
python main.py
```

### Slack Commands

Mention the bot with a receipt PDF attached:
```
@FinanceBot [receipt.pdf] Office supplies for booth construction
```

Optionally specify the department:
```
@FinanceBot [receipt.pdf] Paint for decorations | Department: Booth
```

## Project Structure

```
├── config/          # Configuration and constants
├── services/        # Core service modules
├── models/          # Data models
├── utils/           # Helper utilities
├── credentials/     # API credentials (gitignored)
├── main.py          # Application entry point
└── requirements.txt # Python dependencies
```

## License

Internal use only - Spring Carnival Committee
