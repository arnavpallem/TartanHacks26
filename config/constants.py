"""
Club-specific constants for Spring Carnival Committee.
"""

# Organization Details
ORG_NAME = "Spring Carnival Committee"
ACCOUNT_TYPE = "Agency"
TRANSACTION_TYPE = "PCard/Travel Card/HazMat Card"
PREPARER_FIRST_NAME = "Arnav"
PREPARER_LAST_NAME = "Pallem"
PREPARER_WHO_FORMAT = "A Pallem"  # First initial + Last name

# Budget Sheet Names
BUDGET_SHEETS = [
    "Misc Line Items",
    "Operations Line Items", 
    "Electrical Line Items",
    "Booth Line Items",
    "Entertainment Line Items",
]

# Department keywords for line item matching
DEPARTMENT_KEYWORDS = {
    "Misc": ["misc", "general", "office", "admin", "gbm", "meeting", "exec", "stoles", "subscription", "slack", "google", "workspace", "software", "saas", "online"],
    "Operations": ["operations", "ops", "logistics", "equipment", "tools", "supplies"],
    "Electrical": ["electrical", "electric", "power", "lights", "wiring", "cables"],
    "Booth": ["booth", "construction", "paint", "lumber", "hardware", "decorations"],
    "Entertainment": ["entertainment", "music", "audio", "video", "performance", "show", "speaker", "dj"],
}

# TPR Tracking Sheet columns (0-indexed)
TPR_TRACKING_COLS = {
    "description": 1,  # Column B
    "amount": 2,       # Column C
    "tpr_number": 3,   # Column D
}

# Budget Sheet columns (0-indexed) 
BUDGET_SHEET_COLS = {
    "description": 0,  # Column A
    "actual": 1,       # Column B
    "receipt_link": 6, # Column G
}

# Gmail monitoring
GMAIL_CHECK_INTERVAL_HOURS = 24
RECEIPT_KEYWORDS = [
    "receipt",
    "order confirmation", 
    "invoice",
    "purchase confirmation",
    "payment confirmation",
]
RECEIPT_SENDERS = [
    "amazon",
    "costco",
    "homedepot",
    "lowes",
    "walmart",
    "target",
    "dominos",
    "uber",
]
