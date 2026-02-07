"""
Test script for VLM-based receipt processing using Gemini.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from services.ocr_processor import extract_receipt_data


def test_vlm_extraction():
    """Test VLM extraction with a sample receipt."""
    print("=" * 60)
    print("VLM Receipt Extraction Test (Gemini)")
    print("=" * 60)
    
    # Find a test receipt in temp directory
    temp_dir = Path(__file__).parent / "temp"
    pdf_files = list(temp_dir.glob("*.pdf"))
    
    if not pdf_files:
        print("\n❌ No PDF files found in temp/ directory")
        print("   Please add a receipt PDF to temp/ and try again")
        return False
    
    # Use the first PDF found
    test_pdf = pdf_files[0]
    print(f"\n📄 Testing with: {test_pdf.name}")
    
    try:
        # Extract receipt data
        print("\n🔍 Extracting data with Gemini VLM...")
        receipt = extract_receipt_data(test_pdf)
        
        print("\n✅ Extraction successful!")
        print("\n📋 Extracted Fields:")
        print(f"   Vendor:           {receipt.vendor}")
        print(f"   Date:             {receipt.formatted_date}")
        print(f"   Amount:           ${receipt.formatted_amount}")
        print(f"   Category:         {receipt.category}")
        print(f"   Description:      {receipt.short_description}")
        print(f"   Is Food:          {receipt.is_food}")
        print(f"   Is Travel:        {receipt.is_travel}")
        
        print("\n" + "=" * 60)
        print("Test complete!")
        print("=" * 60)
        return True
        
    except ValueError as e:
        print(f"\n❌ Configuration error: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_vlm_extraction()
    sys.exit(0 if success else 1)
