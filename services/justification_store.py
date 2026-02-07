"""
Justification store for recurring purchases.
Stores and matches vendor justifications using fuzzy matching.
"""
import json
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from rapidfuzz import fuzz

from config.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Storage file path
JUSTIFICATIONS_FILE = PROJECT_ROOT / "data" / "recurring_justifications.json"

# Fuzzy match threshold (0-100)
MATCH_THRESHOLD = 80


@dataclass
class SavedJustification:
    """A saved justification for a recurring vendor."""
    vendor_pattern: str
    justification: str
    category: str


def load_justifications() -> list[SavedJustification]:
    """Load all saved justifications from the JSON file."""
    if not JUSTIFICATIONS_FILE.exists():
        return []
    
    try:
        with open(JUSTIFICATIONS_FILE, 'r') as f:
            data = json.load(f)
        
        return [
            SavedJustification(
                vendor_pattern=v.get("vendor_pattern", ""),
                justification=v.get("justification", ""),
                category=v.get("category", "Misc")
            )
            for v in data.get("vendors", [])
        ]
    except Exception as e:
        logger.error(f"Error loading justifications: {e}")
        return []


def save_justification(vendor: str, justification: str, category: str = "Misc") -> bool:
    """
    Save a new recurring justification.
    
    Args:
        vendor: Vendor name (will be stored as lowercase pattern)
        justification: The justification text
        category: Budget category
        
    Returns:
        True if saved successfully
    """
    # Load existing
    existing = load_justifications()
    
    # Check if vendor already exists (update if so)
    vendor_lower = vendor.lower().strip()
    updated = False
    
    for saved in existing:
        if fuzz.ratio(saved.vendor_pattern, vendor_lower) > MATCH_THRESHOLD:
            # Update existing
            saved.justification = justification
            saved.category = category
            updated = True
            logger.info(f"Updated justification for vendor: {vendor}")
            break
    
    if not updated:
        # Add new
        existing.append(SavedJustification(
            vendor_pattern=vendor_lower,
            justification=justification,
            category=category
        ))
        logger.info(f"Saved new justification for vendor: {vendor}")
    
    # Save to file
    try:
        # Ensure directory exists
        JUSTIFICATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "vendors": [
                {
                    "vendor_pattern": s.vendor_pattern,
                    "justification": s.justification,
                    "category": s.category
                }
                for s in existing
            ]
        }
        
        with open(JUSTIFICATIONS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        
        return True
    except Exception as e:
        logger.error(f"Error saving justification: {e}")
        return False


def find_matching_justification(vendor: str) -> tuple[Optional[SavedJustification], int]:
    """
    Find a saved justification that matches the vendor.
    
    Args:
        vendor: Vendor name to match
        
    Returns:
        Tuple of (Matching SavedJustification or None, match score 0-100)
    """
    if not vendor:
        return None, 0
    
    vendor_lower = vendor.lower().strip()
    saved = load_justifications()
    
    best_match = None
    best_score = 0
    
    for s in saved:
        # Use partial ratio for flexibility (e.g., "Slack" matches "Slack Technologies")
        score = fuzz.partial_ratio(s.vendor_pattern, vendor_lower)
        
        if score > MATCH_THRESHOLD and score > best_score:
            best_score = score
            best_match = s
    
    if best_match:
        logger.info(f"Found matching justification for '{vendor}' -> '{best_match.vendor_pattern}' (score: {best_score})")
    
    return best_match, best_score


def list_saved_vendors() -> list[str]:
    """Return list of all saved vendor patterns."""
    return [s.vendor_pattern for s in load_justifications()]

