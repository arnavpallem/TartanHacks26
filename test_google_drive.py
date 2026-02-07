"""
Test script for Google Drive integration.
Run this to verify Google Drive authentication and folder access.
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from services.google_drive import GoogleDriveService
from config.settings import FilePathConfig


def test_google_drive():
    """Test Google Drive connection and folder access."""
    print("=" * 60)
    print("Google Drive Integration Test")
    print("=" * 60)
    
    # Initialize service
    print("\n1. Initializing Google Drive service...")
    try:
        drive_service = GoogleDriveService()
        print("   ✅ Service initialized")
    except Exception as e:
        print(f"   ❌ Failed to initialize: {e}")
        return False
    
    # Authenticate
    print("\n2. Authenticating with Google...")
    print("   (A browser window may open for OAuth if this is the first time)")
    try:
        drive_service.authenticate()
        print("   ✅ Authentication successful")
    except Exception as e:
        print(f"   ❌ Authentication failed: {e}")
        return False
    
    # List root files
    print("\n3. Testing API access - listing root files...")
    try:
        results = drive_service.service.files().list(
            pageSize=5,
            fields="files(id, name, mimeType, starred)"
        ).execute()
        files = results.get('files', [])
        
        if files:
            print(f"   ✅ Found {len(files)} files:")
            for f in files:
                is_folder = "📁" if f.get('mimeType') == 'application/vnd.google-apps.folder' else "📄"
                is_starred = "⭐" if f.get('starred') else ""
                print(f"      {is_folder} {f['name']} {is_starred}")
        else:
            print("   ⚠️ No files found in root (this might be okay)")
    except Exception as e:
        print(f"   ❌ Failed to list files: {e}")
        return False
    
    # Check configured receipts folder
    print(f"\n4. Looking for receipts folder: '{FilePathConfig.RECEIPTS_FOLDER}'")
    
    # Search for Spring Carnival 2026 (could be a shortcut or folder)
    print("   Searching for 'Spring Carnival 2026'...")
    target_folder_id = None
    
    try:
        results = drive_service.service.files().list(
            q="name = 'Spring Carnival 2026'",
            spaces='drive',
            fields='files(id, name, mimeType, shortcutDetails)',
            pageSize=10
        ).execute()
        
        found_items = results.get('files', [])
        if found_items:
            for f in found_items:
                mime_type = f.get('mimeType', '')
                
                # Check if it's a shortcut
                if mime_type == 'application/vnd.google-apps.shortcut':
                    shortcut_details = f.get('shortcutDetails', {})
                    target_id = shortcut_details.get('targetId')
                    target_mime = shortcut_details.get('targetMimeType', '')
                    print(f"   📎 Found shortcut: {f['name']}")
                    print(f"      Target ID: {target_id[:20] if target_id else 'None'}...")
                    print(f"      Target type: {target_mime}")
                    
                    if target_mime == 'application/vnd.google-apps.folder':
                        target_folder_id = target_id
                        print(f"   ✅ Resolved shortcut to folder ID!")
                        
                # Check if it's a folder directly
                elif mime_type == 'application/vnd.google-apps.folder':
                    target_folder_id = f['id']
                    print(f"   📁 Found folder directly: {f['name']}")
                    print(f"      Folder ID: {target_folder_id[:20]}...")
        else:
            print("   ⚠️ No items found with exact name 'Spring Carnival 2026'")
            
    except Exception as e:
        print(f"   ❌ Error searching: {e}")
    
    # If we found the Spring Carnival folder, navigate to Finance/Receipts/Invoices
    if target_folder_id:
        print("\n   Navigating folder path: Finance -> Receipts/Invoices...")
        path_parts = ['Finance', 'Receipts/Invoices']
        current_folder_id = target_folder_id
        
        for folder_name in path_parts:
            try:
                results = drive_service.service.files().list(
                    q=f"'{current_folder_id}' in parents and name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder'",
                    spaces='drive',
                    fields='files(id, name)',
                    pageSize=5,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()
                
                folders = results.get('files', [])
                if folders:
                    current_folder_id = folders[0]['id']
                    print(f"      ✅ Found '{folder_name}' (ID: {current_folder_id[:15]}...)")
                else:
                    print(f"      ❌ Could not find '{folder_name}' folder")
                    print(f"         Listing contents of current folder...")
                    
                    # List what's in the current folder to help debug
                    results = drive_service.service.files().list(
                        q=f"'{current_folder_id}' in parents",
                        spaces='drive',
                        fields='files(id, name, mimeType)',
                        pageSize=20,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True
                    ).execute()
                    
                    contents = results.get('files', [])
                    if contents:
                        print(f"         Available items:")
                        for item in contents:
                            icon = "📁" if item.get('mimeType') == 'application/vnd.google-apps.folder' else "📄"
                            print(f"            {icon} {item['name']}")
                    else:
                        print(f"         (folder appears empty or no access)")
                    break
                    
            except Exception as e:
                print(f"      ❌ Error navigating to '{folder_name}': {e}")
                break
        else:
            # Successfully navigated all folders
            print(f"\n   🎉 Successfully found Invoices folder!")
            print(f"      Final folder ID: {current_folder_id}")
            
            # List contents of Invoices folder
            try:
                results = drive_service.service.files().list(
                    q=f"'{current_folder_id}' in parents",
                    spaces='drive',
                    fields='files(id, name, mimeType)',
                    pageSize=10
                ).execute()
                
                invoices = results.get('files', [])
                if invoices:
                    print(f"      Contents ({len(invoices)} items):")
                    for inv in invoices:
                        icon = "📁" if inv.get('mimeType') == 'application/vnd.google-apps.folder' else "📄"
                        print(f"         {icon} {inv['name']}")
                else:
                    print(f"      (folder is empty)")
            except Exception as e:
                print(f"      ❌ Error listing contents: {e}")
    else:
        print("\n   ⚠️ Could not locate Spring Carnival 2026 folder")
    
    # Test file upload (dry run - just check we can generate upload metadata)
    print("\n5. Testing upload capability...")
    try:
        # Just verify we can create a file metadata object
        from googleapiclient.http import MediaFileUpload
        print("   ✅ Upload modules available")
    except Exception as e:
        print(f"   ❌ Upload capability issue: {e}")
    
    # Test the actual service methods
    print("\n6. Testing GoogleDriveService._find_folder_by_path()...")
    try:
        # Test with the configured RECEIPTS_FOLDER path (uses | delimiter)
        folder_id = drive_service._find_folder_by_path(FilePathConfig.RECEIPTS_FOLDER)
        if folder_id:
            print(f"   ✅ Found Receipts folder via service method")
            print(f"      Path: {FilePathConfig.RECEIPTS_FOLDER}")
            print(f"      Folder ID: {folder_id[:20]}...")
        else:
            print(f"   ❌ _find_folder_by_path returned None")
            print(f"      Path: {FilePathConfig.RECEIPTS_FOLDER}")
    except Exception as e:
        print(f"   ❌ Error in _find_folder_by_path: {e}")
    
    # Test GoogleSheetsService
    print("\n7. Testing GoogleSheetsService._find_spreadsheet_by_path()...")
    try:
        from services.google_sheets import GoogleSheetsService
        
        sheets_service = GoogleSheetsService()
        sheets_service.authenticate()
        
        # Test Budget Spreadsheet lookup
        budget_id = sheets_service._find_spreadsheet_by_path(FilePathConfig.BUDGET_SPREADSHEET)
        if budget_id:
            print(f"   ✅ Found Budget spreadsheet via service method")
            print(f"      Path: {FilePathConfig.BUDGET_SPREADSHEET}")
            print(f"      Spreadsheet ID: {budget_id[:20]}...")
        else:
            print(f"   ⚠️ Budget spreadsheet not found (might not exist yet)")
            print(f"      Path: {FilePathConfig.BUDGET_SPREADSHEET}")
        
        # Test TPR Tracking Sheet lookup
        tpr_id = sheets_service._find_spreadsheet_by_path(FilePathConfig.TPR_TRACKING_SHEET)
        if tpr_id:
            print(f"   ✅ Found TPR Tracking sheet via service method")
            print(f"      Path: {FilePathConfig.TPR_TRACKING_SHEET}")
            print(f"      Spreadsheet ID: {tpr_id[:20]}...")
        else:
            print(f"   ⚠️ TPR Tracking sheet not found (might not exist yet)")
            print(f"      Path: {FilePathConfig.TPR_TRACKING_SHEET}")
            
    except Exception as e:
        print(f"   ❌ Error testing sheets service: {e}")
    
    print("\n" + "=" * 60)
    print("Google Drive test complete!")
    print("=" * 60)
    
    return True


if __name__ == "__main__":
    success = test_google_drive()
    sys.exit(0 if success else 1)
