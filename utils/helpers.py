"""
Utility helper functions.
"""
import re
from decimal import Decimal
from typing import Optional
from rapidfuzz import fuzz, process

from config.constants import DEPARTMENT_KEYWORDS, BUDGET_SHEETS


def extract_one_word_descriptor(text: str) -> str:
    """
    Extract a short one-word descriptor from a purchase description.
    Removes common filler words and returns the most meaningful word.
    """
    # Common words to ignore
    stop_words = {
        "the", "a", "an", "for", "of", "to", "from", "in", "on", "at",
        "and", "or", "but", "with", "some", "this", "that", "these",
        "spring", "carnival", "committee", "purchase", "bought", "ordered",
    }
    
    # Clean and tokenize
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    
    # Filter out stop words and short words
    meaningful_words = [
        word for word in words 
        if word not in stop_words and len(word) > 2
    ]
    
    if meaningful_words:
        # Return the first meaningful word, capitalized
        return meaningful_words[0].capitalize()
    
    # Fallback
    return "Supplies"


def match_department(description: str, explicit_department: Optional[str] = None) -> str:
    """
    Match a purchase description to a department/budget sheet.
    
    Args:
        description: The purchase description
        explicit_department: User-specified department (takes priority)
        
    Returns:
        The matching budget sheet name (e.g., "Misc Line Items")
    """
    if explicit_department:
        # Try to match explicit department to sheet name
        explicit_lower = explicit_department.lower()
        for sheet_name in BUDGET_SHEETS:
            dept_name = sheet_name.replace(" Line Items", "").lower()
            if dept_name in explicit_lower or explicit_lower in dept_name:
                return sheet_name
    
    # Use keyword matching on description
    description_lower = description.lower()
    best_match = None
    best_score = 0
    
    for dept, keywords in DEPARTMENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in description_lower:
                # Direct keyword match - high priority
                score = 100
                if score > best_score:
                    best_score = score
                    best_match = f"{dept} Line Items"
    
    if best_match:
        return best_match
    
    # Fuzzy matching as fallback
    all_keywords = []
    keyword_to_dept = {}
    for dept, keywords in DEPARTMENT_KEYWORDS.items():
        for keyword in keywords:
            all_keywords.append(keyword)
            keyword_to_dept[keyword] = dept
    
    result = process.extractOne(description_lower, all_keywords, scorer=fuzz.partial_ratio)
    if result and result[1] > 60:
        matched_keyword = result[0]
        dept = keyword_to_dept[matched_keyword]
        return f"{dept} Line Items"
    
    # Default to Misc
    return "Misc Line Items"


def parse_amount(amount_str: str) -> Optional[Decimal]:
    """
    Parse a string amount to Decimal.
    Handles various formats: $1,234.56, 1234.56, $12.34, etc.
    """
    if not amount_str:
        return None
    
    # Remove currency symbols and whitespace
    cleaned = re.sub(r'[$£€\s,]', '', amount_str)
    
    try:
        return Decimal(cleaned)
    except Exception:
        return None


def format_amount_for_tpr(amount: Decimal) -> str:
    """Format amount as xxx.xx for TPR form."""
    return f"{amount:.2f}"


def sanitize_for_tpr(text: str) -> str:
    """
    Sanitize text for TPR form fields.
    The TPR form is very strict and doesn't accept any punctuation.
    Keeps only alphanumeric characters and spaces.
    """
    if not text:
        return ""
    
    # Remove ALL punctuation - keep only letters, numbers, and spaces
    sanitized = re.sub(r'[^a-zA-Z0-9\s]', ' ', text)
    
    # Clean up multiple spaces
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    return sanitized


def sanitize_filename(filename: str) -> str:
    """Remove or replace invalid characters from filename."""
    # Replace invalid characters with underscores
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip('. ')
    return sanitized or "receipt"


def generate_receipt_filename(
    vendor: str, 
    date_str: str, 
    amount: Decimal,
    department: str = "Misc"
) -> str:
    """
    Generate a standardized receipt filename.
    Format: Department_Vendor_Amount_MM-DD-YY.pdf
    
    Args:
        vendor: Vendor name
        date_str: Date string (will be converted to MM-DD-YY)
        amount: Purchase amount
        department: Budget department (default: Misc)
        
    Returns:
        Formatted filename
    """
    # Clean department (remove "Line Items" suffix if present)
    dept_clean = sanitize_filename(department.replace(" Line Items", ""))[:15]
    
    # Clean vendor name (first word only, max 20 chars)
    vendor_clean = sanitize_filename(vendor.split()[0] if vendor else "Unknown")[:20]
    
    # Format amount (no decimal point for clean filename)
    amount_str = f"{amount:.2f}".replace(".", "_")
    
    # Parse and format date as MM-DD-YY
    from datetime import datetime
    try:
        # Try to parse various date formats
        for fmt in ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                date_formatted = dt.strftime("%m-%d-%y")
                break
            except ValueError:
                continue
        else:
            # If no format matched, use today
            date_formatted = datetime.now().strftime("%m-%d-%y")
    except Exception:
        date_formatted = datetime.now().strftime("%m-%d-%y")
    
    return f"{dept_clean}_{vendor_clean}_{amount_str}_{date_formatted}.pdf"
