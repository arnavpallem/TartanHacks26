"""
Google Sheets integration for updating budget and TPR tracking sheets.
"""
import logging
from typing import Optional, List, Tuple

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from pathlib import Path

from config.settings import GoogleConfig, FilePathConfig
from config.constants import (
    BUDGET_SHEETS, BUDGET_SHEET_COLS, TPR_TRACKING_COLS, DEPARTMENT_KEYWORDS
)
from models.receipt import Purchase
from utils.helpers import match_department

logger = logging.getLogger(__name__)


class GoogleSheetsService:
    """Service for interacting with Google Sheets API."""
    
    def __init__(self):
        self.creds: Optional[Credentials] = None
        self.service = None
        self._budget_spreadsheet_id: Optional[str] = None
        self._tpr_tracking_id: Optional[str] = None
    
    def authenticate(self):
        """Authenticate with Google Sheets API using OAuth."""
        creds = None
        token_path = Path(GoogleConfig.TOKEN_PATH)
        
        # Load existing token if available
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(token_path), GoogleConfig.SCOPES
            )
        
        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    GoogleConfig.CREDENTIALS_PATH, GoogleConfig.SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save credentials for next run
            token_path.write_text(creds.to_json())
        
        self.creds = creds
        self.service = build('sheets', 'v4', credentials=creds)
        logger.info("Google Sheets authenticated successfully")
    
    def _find_spreadsheet_by_path(self, path: str) -> Optional[str]:
        """
        Find a spreadsheet ID by searching in Drive.
        Uses the Drive API to find the spreadsheet by name/path.
        Handles shortcuts by resolving them to target spreadsheet.
        Uses '|' as delimiter to support names containing slashes.
        """
        from googleapiclient.discovery import build as build_drive
        drive_service = build_drive('drive', 'v3', credentials=self.creds)
        
        # Use | as delimiter, get the spreadsheet name (last part)
        parts = path.split("|")
        name = parts[-1]
        
        # Search for the spreadsheet or a shortcut to it
        query = f"name = '{name}'"
        
        results = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name, mimeType, shortcutDetails)',
            supportsAllDrives=True,
            includeItemsFromAllDrives=True
        ).execute()
        
        files = results.get('files', [])
        for file in files:
            mime_type = file.get('mimeType', '')
            
            # Check if it's a shortcut
            if mime_type == 'application/vnd.google-apps.shortcut':
                shortcut_details = file.get('shortcutDetails', {})
                target_id = shortcut_details.get('targetId')
                target_mime = shortcut_details.get('targetMimeType', '')
                
                if target_mime == 'application/vnd.google-apps.spreadsheet' and target_id:
                    logger.info(f"Resolved shortcut '{name}' to spreadsheet ID: {target_id[:15]}...")
                    return target_id
            
            # Direct spreadsheet match
            elif mime_type == 'application/vnd.google-apps.spreadsheet':
                return file['id']
        
        return None
    
    def get_budget_spreadsheet_id(self) -> str:
        """Get the budget spreadsheet ID."""
        if self._budget_spreadsheet_id:
            return self._budget_spreadsheet_id
        
        spreadsheet_id = self._find_spreadsheet_by_path(FilePathConfig.BUDGET_SPREADSHEET)
        if spreadsheet_id:
            self._budget_spreadsheet_id = spreadsheet_id
            return spreadsheet_id
        
        raise ValueError(f"Budget spreadsheet not found: {FilePathConfig.BUDGET_SPREADSHEET}")
    
    def get_tpr_tracking_id(self) -> str:
        """Get the TPR tracking spreadsheet ID."""
        if self._tpr_tracking_id:
            return self._tpr_tracking_id
        
        spreadsheet_id = self._find_spreadsheet_by_path(FilePathConfig.TPR_TRACKING_SHEET)
        if spreadsheet_id:
            self._tpr_tracking_id = spreadsheet_id
            return spreadsheet_id
        
        raise ValueError(f"TPR tracking sheet not found: {FilePathConfig.TPR_TRACKING_SHEET}")
    
    def get_sheet_data(self, spreadsheet_id: str, sheet_name: str) -> List[List[str]]:
        """Get all data from a sheet."""
        result = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A:G"
        ).execute()
        return result.get('values', [])
    
    def find_line_item_row(self, sheet_name: str, description: str, vendor: str = "", amount: float = 0, category: str = "", justification: str = "") -> Tuple[int, str]:
        """
        Find the row number of the best matching line item in a budget sheet.
        Line items are bold rows that serve as category headers.
        Uses LLM for intelligent classification.
        
        Returns:
            Tuple of (row_number, line_item_name)
        """
        spreadsheet_id = self.get_budget_spreadsheet_id()
        data = self.get_sheet_data(spreadsheet_id, sheet_name)
        
        # Get cell formatting to identify bold (line item) rows
        sheet_metadata = self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            ranges=[f"'{sheet_name}'!A:A"],
            includeGridData=True
        ).execute()
        
        # Find bold rows (line items)
        bold_rows = []
        grid_data = sheet_metadata.get('sheets', [{}])[0].get('data', [{}])[0]
        row_data = grid_data.get('rowData', [])
        
        for i, row in enumerate(row_data):
            cells = row.get('values', [])
            if cells:
                cell = cells[0]
                format_data = cell.get('effectiveFormat', {})
                text_format = format_data.get('textFormat', {})
                if text_format.get('bold', False):
                    cell_value = cell.get('formattedValue', '')
                    if cell_value:
                        bold_rows.append((i + 1, cell_value))  # 1-indexed
        
        # Use LLM classifier to match line item
        if bold_rows:
            from services.line_item_classifier import classify_line_item
            
            # Filter out invalid line items (headers, totals, etc.)
            invalid_patterns = ["grand total", "total", "subtotal", "summary"]
            valid_rows = [
                (row_num, name) for row_num, name in bold_rows
                if name.lower().strip() not in invalid_patterns
                and not name.lower().startswith("total")
                and len(name.strip()) > 2
            ]
            
            if not valid_rows:
                valid_rows = bold_rows  # Fallback to all if filtering removes everything
            
            line_item_names = [row[1] for row in valid_rows]
            
            # Use LLM to classify
            matched_name = classify_line_item(
                vendor=vendor,
                amount=amount,
                description=description,
                category=category,
                line_items=line_item_names,
                justification=justification
            )
            
            # Find the row number for the matched name
            for row_num, name in bold_rows:
                if name == matched_name:
                    return (row_num, name)
        
        # Default to first line item if no match
        if bold_rows:
            return bold_rows[0]
        
        return (2, "Unknown")  # Default to row 2
    
    def insert_row_above(self, spreadsheet_id: str, sheet_name: str, row_number: int):
        """Insert an empty row above the specified row."""
        # Get sheet ID
        sheet_metadata = self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id
        ).execute()
        
        sheet_id = None
        for sheet in sheet_metadata.get('sheets', []):
            if sheet.get('properties', {}).get('title') == sheet_name:
                sheet_id = sheet.get('properties', {}).get('sheetId')
                break
        
        if sheet_id is None:
            raise ValueError(f"Sheet not found: {sheet_name}")
        
        # Insert row
        requests = [{
            'insertDimension': {
                'range': {
                    'sheetId': sheet_id,
                    'dimension': 'ROWS',
                    'startIndex': row_number - 1,  # 0-indexed
                    'endIndex': row_number
                },
                'inheritFromBefore': False
            }
        }]
        
        self.service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={'requests': requests}
        ).execute()
    
    def update_budget_sheet(self, purchase: Purchase):
        """
        Add a purchase to the appropriate budget sheet.
        
        1. Determine which sheet based on department/description
        2. Find the matching line item
        3. Move one row up from line item, then insert above (preserves formatting)
        4. Fill in the purchase details with vendor+date name and HYPERLINK chip
        """
        if not self.service:
            self.authenticate()
        
        spreadsheet_id = self.get_budget_spreadsheet_id()
        
        # Determine which sheet to use
        sheet_name = match_department(purchase.description, purchase.department)
        logger.info(f"Matched to sheet: {sheet_name}")
        
        # Find the line item row using LLM classification
        line_item_row, line_item_name = self.find_line_item_row(
            sheet_name=sheet_name,
            description=purchase.description,
            vendor=purchase.vendor,
            amount=float(purchase.amount),
            category=purchase.department or "",
            justification=purchase.justification
        )
        logger.info(f"LLM matched to line item: {line_item_name} (row {line_item_row})")
        
        # Insert row ONE ABOVE the line item (move up first, then insert)
        # This preserves formatting by inserting between existing data row and line item
        insert_at_row = line_item_row - 1 if line_item_row > 2 else line_item_row
        self.insert_row_above(spreadsheet_id, sheet_name, insert_at_row)
        
        # Create HYPERLINK formula for clickable link chip
        if purchase.receipt_link:
            # HYPERLINK formula creates a clickable chip in Google Sheets
            link_formula = f'=HYPERLINK("{purchase.receipt_link}", "Receipt")'
        else:
            link_formula = ''
        
        # Fill in the new row (now at insert_at_row)
        # Use display_name (vendor + date) instead of description
        values = [
            [
                purchase.display_name,          # Column A - Vendor + Date name
                purchase.amount_negative,       # Column B - Actual (negative)
                '',                             # Column C
                '',                             # Column D
                '',                             # Column E
                '',                             # Column F
                link_formula                    # Column G - Receipt link as HYPERLINK chip
            ]
        ]
        
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A{insert_at_row}:G{insert_at_row}",
            valueInputOption='USER_ENTERED',
            body={'values': values}
        ).execute()
        
        logger.info(f"Updated budget sheet: {purchase.display_name}")
    
    def update_tpr_tracking(self, purchase: Purchase):
        """
        Add a purchase to the TPR tracking sheet.
        
        Columns: B=Name (Vendor+Date), C=Amount, D=TPR#
        (Skip A=Person and E=Reimbursement)
        """
        if not self.service:
            self.authenticate()
        
        spreadsheet_id = self.get_tpr_tracking_id()
        
        # Get the first sheet name from the spreadsheet
        spreadsheet_meta = self.service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields='sheets.properties.title'
        ).execute()
        
        sheets = spreadsheet_meta.get('sheets', [])
        if not sheets:
            raise ValueError("No sheets found in TPR tracking spreadsheet")
        
        sheet_name = sheets[0]['properties']['title']
        logger.info(f"Using sheet name: {sheet_name}")
        
        # Append new row - use display_name (vendor + date)
        values = [
            [
                '',                          # Column A - Person (skip)
                purchase.display_name,       # Column B - Vendor + Date name
                float(purchase.amount),      # Column C - Amount
                purchase.tpr_number,         # Column D - TPR #
                ''                           # Column E - Reimbursement (skip)
            ]
        ]
        
        self.service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A:E",
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': values}
        ).execute()
        
        logger.info(f"Updated TPR tracking: {purchase.display_name} - {purchase.tpr_number}")


# Global instance
_sheets_service: Optional[GoogleSheetsService] = None


def get_sheets_service() -> GoogleSheetsService:
    """Get the global Google Sheets service instance."""
    global _sheets_service
    if _sheets_service is None:
        _sheets_service = GoogleSheetsService()
        _sheets_service.authenticate()
    return _sheets_service


async def update_budget(purchase: Purchase):
    """Update the budget sheet with a new purchase."""
    service = get_sheets_service()
    service.update_budget_sheet(purchase)


async def update_tpr_tracking(purchase: Purchase):
    """Update the TPR tracking sheet with a new purchase."""
    service = get_sheets_service()
    service.update_tpr_tracking(purchase)
