"""
Google Drive integration for uploading receipts and getting shareable links.
"""
import logging
from pathlib import Path
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config.settings import GoogleConfig, FilePathConfig

logger = logging.getLogger(__name__)


class GoogleDriveService:
    """Service for interacting with Google Drive API."""
    
    def __init__(self):
        self.creds: Optional[Credentials] = None
        self.service = None
        self._receipts_folder_id: Optional[str] = None
    
    def authenticate(self):
        """Authenticate with Google Drive API using OAuth."""
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
        self.service = build('drive', 'v3', credentials=creds)
        logger.info("Google Drive authenticated successfully")
    
    def _find_folder_by_path(self, path: str) -> Optional[str]:
        """
        Find a folder ID by its path (e.g., "Folder1|Folder2|Folder3").
        
        Uses '|' as delimiter to support folder names containing slashes.
        Handles shortcuts by resolving them to their target folder.
        """
        # Use | as delimiter to support folder names with slashes
        parts = path.split("|")
        
        parent_id = None
        
        for i, part in enumerate(parts):
            # Build query - include shortcuts in search
            query = f"name = '{part}'"
            if parent_id:
                query += f" and '{parent_id}' in parents"
            
            # Request shortcutDetails to handle shortcuts
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, mimeType, shortcutDetails)',
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            
            files = results.get('files', [])
            if not files:
                logger.warning(f"Folder not found: {part}")
                return None
            
            # Check if it's a shortcut and resolve it
            file = files[0]
            mime_type = file.get('mimeType', '')
            
            if mime_type == 'application/vnd.google-apps.shortcut':
                # Resolve shortcut to target
                shortcut_details = file.get('shortcutDetails', {})
                target_id = shortcut_details.get('targetId')
                target_mime = shortcut_details.get('targetMimeType', '')
                
                if target_mime == 'application/vnd.google-apps.folder' and target_id:
                    parent_id = target_id
                    logger.info(f"Resolved shortcut '{part}' to folder ID: {target_id[:15]}...")
                else:
                    logger.warning(f"Shortcut '{part}' does not point to a folder")
                    return None
            elif mime_type == 'application/vnd.google-apps.folder':
                parent_id = file['id']
            else:
                # Not a folder, skip if not last item
                if i < len(parts) - 1:
                    logger.warning(f"'{part}' is not a folder: {mime_type}")
                    return None
                parent_id = file['id']
        
        return parent_id
    
    def find_folder_by_path(self, path: str) -> Optional[str]:
        """Public method to find a folder ID by path."""
        return self._find_folder_by_path(path)
    
    def get_receipts_folder_id(self) -> str:
        """Get or find the receipts folder ID."""
        if self._receipts_folder_id:
            return self._receipts_folder_id
        
        folder_id = self._find_folder_by_path(FilePathConfig.RECEIPTS_FOLDER)
        if folder_id:
            self._receipts_folder_id = folder_id
            return folder_id
        
        raise ValueError(f"Receipts folder not found: {FilePathConfig.RECEIPTS_FOLDER}")
    
    def upload_receipt(self, file_path: Path, filename: str = None) -> str:
        """
        Upload a receipt file to Google Drive.
        
        Args:
            file_path: Path to the file to upload
            filename: Optional custom filename
            
        Returns:
            Shareable link to the uploaded file
        """
        if not self.service:
            self.authenticate()
        
        filename = filename or file_path.name
        folder_id = self.get_receipts_folder_id()
        
        # File metadata
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        
        # Determine MIME type
        mime_type = 'application/pdf' if filename.endswith('.pdf') else 'application/octet-stream'
        
        # Upload file
        media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)
        
        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()
        
        file_id = file.get('id')
        web_link = file.get('webViewLink')
        
        logger.info(f"Uploaded file: {filename} (ID: {file_id})")
        
        # Set permissions to anyone with link can view
        self.service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'},
            supportsAllDrives=True
        ).execute()
        
        return web_link
    
    def get_shareable_link(self, file_id: str) -> str:
        """Get a shareable link for an existing file."""
        file = self.service.files().get(
            fileId=file_id,
            fields='webViewLink',
            supportsAllDrives=True
        ).execute()
        return file.get('webViewLink', '')


# Global instance
_drive_service: Optional[GoogleDriveService] = None


def get_drive_service() -> GoogleDriveService:
    """Get the global Google Drive service instance."""
    global _drive_service
    if _drive_service is None:
        _drive_service = GoogleDriveService()
        _drive_service.authenticate()
    return _drive_service


async def upload_receipt_to_drive(file_path: Path, filename: str = None) -> str:
    """
    Upload a receipt to Google Drive and return the shareable link.
    
    Args:
        file_path: Path to the receipt file
        filename: Optional custom filename
        
    Returns:
        Shareable link to the uploaded file
    """
    service = get_drive_service()
    return service.upload_receipt(file_path, filename)
