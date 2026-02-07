"""
Test script for Google Sheets integration.
Tests the budget and TPR tracking sheet updates with a dummy TPR number.
"""
import sys
import asyncio
from pathlib import Path
from decimal import Decimal
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from models.receipt import Purchase
from services.google_sheets import get_sheets_service, update_budget, update_tpr_tracking


def test_sheets_update():
    """Test updating budget and TPR tracking sheets with dummy data."""
    print("=" * 60)
    print("Google Sheets Update Test")
    print("=" * 60)
    
    # Create a dummy purchase
    dummy_purchase = Purchase(
        description="Test Purchase - Dunkin Donuts for GBM",
        amount=Decimal("87.18"),
        receipt_link="https://drive.google.com/example-receipt-link",
        tpr_number="TPR123456",  # Dummy TPR number
        department="Misc",  # This determines which budget sheet
        date=datetime.now()
    )
    
    print(f"\n📋 Test Purchase Details:")
    print(f"   Description: {dummy_purchase.description}")
    print(f"   Amount: ${dummy_purchase.amount}")
    print(f"   TPR Number: {dummy_purchase.tpr_number}")
    print(f"   Department: {dummy_purchase.department}")
    print(f"   Receipt Link: {dummy_purchase.receipt_link}")
    
    # Test authentication
    print("\n1. Authenticating with Google Sheets...")
    try:
        service = get_sheets_service()
        print("   ✅ Authentication successful")
    except Exception as e:
        print(f"   ❌ Authentication failed: {e}")
        return False
    
    # Test getting spreadsheet IDs
    print("\n2. Getting spreadsheet IDs...")
    try:
        budget_id = service.get_budget_spreadsheet_id()
        print(f"   ✅ Budget Spreadsheet ID: {budget_id[:20]}...")
    except Exception as e:
        print(f"   ❌ Failed to get budget spreadsheet: {e}")
        budget_id = None
    
    try:
        tpr_id = service.get_tpr_tracking_id()
        print(f"   ✅ TPR Tracking Sheet ID: {tpr_id[:20]}...")
    except Exception as e:
        print(f"   ❌ Failed to get TPR tracking sheet: {e}")
        tpr_id = None
    
    # Test updating budget sheet
    print("\n3. Testing Budget Sheet Update...")
    try:
        service.update_budget_sheet(dummy_purchase)
        print("   ✅ Budget sheet updated successfully!")
    except Exception as e:
        print(f"   ❌ Budget sheet update failed: {e}")
    
    # Test updating TPR tracking sheet
    print("\n4. Testing TPR Tracking Sheet Update...")
    try:
        service.update_tpr_tracking(dummy_purchase)
        print("   ✅ TPR tracking sheet updated successfully!")
    except Exception as e:
        print(f"   ❌ TPR tracking sheet update failed: {e}")
    
    print("\n" + "=" * 60)
    print("Test complete! Check your Google Sheets to verify the entries.")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    success = test_sheets_update()
    sys.exit(0 if success else 1)
