"""
VLM-based Receipt Processor using Google Gemini.
Extracts structured data from receipt PDFs/images using vision AI.
"""
import json
import logging
import base64
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from typing import Optional

from PIL import Image
from pdf2image import convert_from_path
import google.generativeai as genai

from models.receipt import ReceiptData
from config.settings import TEMP_DIR, GeminiConfig

logger = logging.getLogger(__name__)

# Configure Gemini
genai.configure(api_key=GeminiConfig.API_KEY)

# Valid budget categories
VALID_CATEGORIES = ["Misc", "Operations", "Electrical", "Booth", "Entertainment"]

# VLM extraction prompt
EXTRACTION_PROMPT = """You are a receipt data extractor. Analyze this receipt image and extract the following information.

Return ONLY valid JSON in this exact format, no other text:
{
  "vendor": "Store or company name (not email headers or 'order from' text)",
  "date": "MM/DD/YYYY format",
  "amount": 0.00,
  "category": "One of: Misc, Operations, Electrical, Booth, Entertainment",
  "short_description": "2-4 word description of main items purchased",
  "is_food": true or false,
  "is_travel": true or false
}

Category guidelines:
- Misc: Office supplies, meeting expenses, GBM food (donuts, pizza, snacks), admin items, stoles, general purchases
- Operations: Logistics, equipment, tools, general supplies, safety equipment
- Electrical: Power, lights, wiring, cables, electrical equipment, generators
- Booth: Construction materials, paint, lumber, hardware, decorations, building supplies
- Entertainment: Music, audio, video, performance equipment, speakers, microphones

Important:
- For "vendor", use the store/company name, not email subject lines or "your order from" text
- For "amount", use the total/grand total, not subtotals
- Set is_food=true for any food purchases (donuts, pizza, catering, etc.)
- Set is_travel=true for transportation, hotels, gas, parking

Return ONLY the JSON object, nothing else."""


def pdf_to_image(pdf_path: Path) -> Image.Image:
    """
    Convert the first page of a PDF to an image.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        PIL Image of the first page
    """
    images = convert_from_path(str(pdf_path), dpi=200, first_page=1, last_page=1)
    if not images:
        raise ValueError(f"Could not convert PDF to image: {pdf_path}")
    return images[0]


def extract_with_gemini(image: Image.Image) -> dict:
    """
    Extract receipt data using Gemini Vision API.
    
    Args:
        image: PIL Image of the receipt
        
    Returns:
        Dictionary with extracted fields
    """
    model = genai.GenerativeModel(GeminiConfig.MODEL)
    
    # Generate response with image
    response = model.generate_content([EXTRACTION_PROMPT, image])
    
    # Parse JSON from response
    response_text = response.text.strip()
    
    # Clean up response - remove markdown code blocks if present
    if response_text.startswith("```"):
        lines = response_text.split("\n")
        # Remove first and last lines (```json and ```)
        response_text = "\n".join(lines[1:-1])
    
    try:
        data = json.loads(response_text)
        logger.info(f"Gemini extracted: {data}")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response: {response_text}")
        raise ValueError(f"Invalid JSON response from Gemini: {e}")


def parse_date(date_str: str) -> datetime:
    """Parse date string in MM/DD/YYYY format."""
    try:
        return datetime.strptime(date_str, "%m/%d/%Y")
    except ValueError:
        # Try alternative formats
        for fmt in ["%m-%d-%Y", "%Y-%m-%d", "%m/%d/%y"]:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        # Default to today if parsing fails
        logger.warning(f"Could not parse date: {date_str}, using today")
        return datetime.now()


def validate_category(category: str) -> str:
    """Validate and normalize the category."""
    if not category:
        return "Misc"
    
    # Title case and strip
    category = category.strip().title()
    
    # Match to valid categories
    for valid in VALID_CATEGORIES:
        if valid.lower() == category.lower():
            return valid
    
    # Fuzzy match
    category_lower = category.lower()
    if "electrical" in category_lower or "electric" in category_lower:
        return "Electrical"
    if "booth" in category_lower or "construction" in category_lower:
        return "Booth"
    if "entertainment" in category_lower or "audio" in category_lower:
        return "Entertainment"
    if "operations" in category_lower or "ops" in category_lower:
        return "Operations"
    
    # Default to Misc
    return "Misc"


def extract_receipt_data(pdf_path: Path) -> ReceiptData:
    """
    Extract all relevant data from a receipt PDF using Gemini Vision.
    
    Args:
        pdf_path: Path to the receipt PDF file
        
    Returns:
        ReceiptData object with extracted information
    """
    logger.info(f"Processing receipt: {pdf_path}")
    
    # Check if Gemini API key is configured
    if not GeminiConfig.API_KEY or GeminiConfig.API_KEY == "your-gemini-api-key-here":
        raise ValueError(
            "Gemini API key not configured. "
            "Get a free API key at https://aistudio.google.com/app/apikey "
            "and add it to your .env file as GEMINI_API_KEY"
        )
    
    # Convert PDF to image
    image = pdf_to_image(pdf_path)
    logger.debug(f"Converted PDF to image: {image.size}")
    
    # Extract data using Gemini
    extracted = extract_with_gemini(image)
    
    # Parse and validate extracted data
    vendor = extracted.get("vendor", "Unknown Vendor")
    date = parse_date(extracted.get("date", datetime.now().strftime("%m/%d/%Y")))
    
    amount_raw = extracted.get("amount", 0)
    try:
        amount = Decimal(str(amount_raw))
    except Exception:
        logger.warning(f"Could not parse amount: {amount_raw}")
        amount = Decimal("0.00")
    
    if amount <= 0:
        raise ValueError(f"Invalid amount extracted: {amount}")
    
    category = validate_category(extracted.get("category", "Misc"))
    short_description = extracted.get("short_description", "")
    is_food = bool(extracted.get("is_food", False))
    is_travel = bool(extracted.get("is_travel", False))
    
    logger.info(
        f"Extracted: vendor={vendor}, date={date}, amount={amount}, "
        f"category={category}, description={short_description}"
    )
    
    return ReceiptData(
        vendor=vendor,
        date=date,
        amount=amount,
        raw_text="",  # No raw text with VLM approach
        file_path=pdf_path,
        category=category,
        short_description=short_description,
        is_food=is_food,
        is_travel=is_travel,
    )


# Legacy function names for backward compatibility
def extract_text_from_pdf(pdf_path: Path) -> str:
    """Legacy function - returns empty string as VLM doesn't use raw text."""
    return ""
