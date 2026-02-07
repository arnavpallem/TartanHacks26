"""
LLM-based Line Item Classifier.
Uses Gemini to classify purchases into the correct budget line item.
"""
import json
import logging
from typing import Optional

import google.generativeai as genai

from config.settings import GeminiConfig

logger = logging.getLogger(__name__)

# Configure Gemini
genai.configure(api_key=GeminiConfig.API_KEY)

# Classification prompt template
CLASSIFICATION_PROMPT = """You are a budget line item classifier. Given a purchase, classify it into the most appropriate line item from the provided list.

**Purchase Details:**
- Vendor: {vendor}
- Amount: ${amount:.2f}
- Description: {description}
- Justification: {justification}
- Category: {category}

**Available Line Items (choose ONE):**
{line_items}

**Instructions:**
1. Pick the SINGLE best matching line item from the list above
2. The justification is very important - use it to understand what the purchase is for
3. For subscriptions (Slack, Google Workspace, etc.), look for "Subscriptions" or "Online" line items
4. Consider the vendor, description, and justification when making your choice
5. If no line item matches well, pick the most general/default one

Return ONLY the exact line item name from the list, nothing else."""


def classify_line_item(
    vendor: str,
    amount: float,
    description: str,
    category: str,
    line_items: list[str],
    justification: str = ""
) -> str:
    """
    Use Gemini to classify a purchase into a budget line item.
    
    Args:
        vendor: Vendor/store name
        amount: Purchase amount
        description: Short description of purchase
        category: Budget category (Misc, Operations, etc.)
        line_items: List of available line items to choose from
        justification: Business justification for the purchase
        
    Returns:
        Best matching line item name
    """
    if not line_items:
        logger.warning("No line items provided for classification")
        return "Unknown"
    
    if len(line_items) == 1:
        return line_items[0]
    
    # Format line items as numbered list
    line_items_formatted = "\n".join(f"- {item}" for item in line_items)
    
    prompt = CLASSIFICATION_PROMPT.format(
        vendor=vendor,
        amount=amount,
        description=description or f"Purchase from {vendor}",
        justification=justification or "Not provided",
        category=category or "Misc",
        line_items=line_items_formatted
    )
    
    try:
        model = genai.GenerativeModel(GeminiConfig.MODEL)
        response = model.generate_content(prompt)
        
        result = response.text.strip()
        
        # Clean up response - remove any extra formatting
        result = result.strip('"\'`')
        
        # Validate result is in our list
        for item in line_items:
            if result.lower() == item.lower():
                logger.info(f"LLM classified '{vendor}' ({justification[:30]}...) as line item: '{item}'")
                return item
        
        # Partial match fallback
        for item in line_items:
            if result.lower() in item.lower() or item.lower() in result.lower():
                logger.info(f"LLM partial match '{result}' -> '{item}'")
                return item
        
        # If no match, log and return first item as fallback
        logger.warning(f"LLM returned '{result}' which doesn't match any line item, using first: {line_items[0]}")
        return line_items[0]
        
    except Exception as e:
        logger.error(f"Error classifying line item: {e}")
        return line_items[0] if line_items else "Unknown"
