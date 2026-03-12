"""
VLM-based Receipt Processor.
Extracts structured data from receipt PDFs/images using vision AI.

"""
import io
import json
import logging
import base64
import os
from pathlib import Path
from datetime import datetime
from decimal import Decimal
from typing import Optional

import requests as http_requests
from PIL import Image
from pdf2image import convert_from_path
import google.generativeai as genai

from models.receipt import ReceiptData
from config.settings import TEMP_DIR, GeminiConfig, OllamaConfig

logger = logging.getLogger(__name__)

# Configure Gemini (only if API key available)
if GeminiConfig.API_KEY:
    genai.configure(api_key=GeminiConfig.API_KEY)

# Valid budget categories
VALID_CATEGORIES = ["Misc", "Operations", "Electrical", "Booth", "Entertainment"]

EXTRACTION_PROMPT = """You are a receipt data extractor. Analyze this receipt image and extract the following information.

Return ONLY valid JSON in this exact format, no other text:
{
  "vendor": "Store or company name (not email headers or 'order from' text)",
  "date": "MM/DD/YYYY format",
  "amount": 0.00,
  "category": "One of: Misc, Operations, Electrical, Booth, Entertainment",
  "short_description": "2-4 word description of main items purchased",
  "is_food": true or false,
  "confidence": 0-100
}

Category guidelines:
- Misc: Office supplies, meeting expenses, GBM food (donuts, pizza, snacks), admin items, stoles, general purchases, online subscriptions (Slack, Google Workspace, etc.)
- Operations: Logistics, equipment, tools, general supplies, safety equipment
- Electrical: Power, lights, wiring, cables, electrical equipment, generators
- Booth: Construction materials, paint, lumber, hardware, decorations, building supplies
- Entertainment: Music, audio, video, performance equipment, speakers, microphones

Confidence scoring (0-100):
- 90-100: All fields clearly visible and unambiguous
- 70-89: Most fields visible, some inference needed
- Below 70: Significant guessing required

Important:
- For "vendor", use the store/company name, not email subject lines or "your order from" text
- For "amount", use the total/grand total, not subtotals
- Set is_food=true for any food purchases (donuts, pizza, catering, etc.)

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


def _clean_json_response(response_text: str) -> dict:
    """
    Clean and parse a JSON response from a VLM.
    Handles markdown code blocks and other formatting.
    """
    text = response_text.strip()
    
    # Remove markdown code blocks if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        text = "\n".join(lines[1:-1])
    
    # Try to extract JSON from the response if it contains other text
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]
    
    return json.loads(text)



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
    
    try:
        data = _clean_json_response(response_text)
        logger.info(f"Gemini extracted: {data}")
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Gemini response: {response_text}")
        raise ValueError(f"Invalid JSON response from Gemini: {e}")


def extract_with_vlm(image: Image.Image) -> dict:
    """
    Hybrid VLM extraction: tries local Ollama first, falls back to Gemini API.
    
    Args:
        image: PIL Image of the receipt
        
    Returns:
        Dictionary with extracted fields
    """
    
    # Fall back to Gemini
    if GeminiConfig.API_KEY and GeminiConfig.API_KEY != "your-gemini-api-key-here":
        logger.info("Using Gemini API for extraction")
        return extract_with_gemini(image)
    
    raise RuntimeError(
        "No VLM backend available. Either start Ollama locally "
        "(ollama serve) or configure GEMINI_API_KEY in .env"
    )


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
    Extract all relevant data from a receipt PDF using VLM (Ollama or Gemini).
    
    Args:
        pdf_path: Path to the receipt PDF file
        
    Returns:
        ReceiptData object with extracted information
    """
    logger.info(f"Processing receipt: {pdf_path}")
    
    # Convert PDF to image
    image = pdf_to_image(pdf_path)
    logger.debug(f"Converted PDF to image: {image.size}")
    
    # Extract data using hybrid VLM (Ollama first, Gemini fallback)
    extracted = extract_with_vlm(image)
    
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
    confidence = int(extracted.get("confidence", 0))
    
    logger.info(
        f"Extracted: vendor={vendor}, date={date}, amount={amount}, "
        f"category={category}, confidence={confidence}%"
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
        confidence=confidence,
    )


# Legacy function names for backward compatibility
def extract_text_from_pdf(pdf_path: Path) -> str:
    """Legacy function - returns empty string as VLM doesn't use raw text."""
    return ""
