"""
Email to PDF conversion for emails without attachment receipts.
Uses WeasyPrint to convert HTML email body to PDF.
"""
import logging
from pathlib import Path
from typing import Optional
import tempfile

logger = logging.getLogger(__name__)


def html_to_pdf(html_content: str, output_path: Optional[Path] = None) -> Path:
    """
    Convert HTML content to a PDF file.
    
    Args:
        html_content: The HTML string to convert
        output_path: Optional output path, creates temp file if not provided
        
    Returns:
        Path to the generated PDF file
    """
    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("weasyprint not installed. Run: pip install weasyprint")
        raise
    
    if output_path is None:
        # Create temp file
        temp_file = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        output_path = Path(temp_file.name)
        temp_file.close()
    
    # Wrap in basic HTML structure if needed
    if '<html' not in html_content.lower():
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; padding: 20px; }}
                img {{ max-width: 100%; }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """
    
    HTML(string=html_content).write_pdf(str(output_path))
    logger.info(f"Converted HTML to PDF: {output_path}")
    
    return output_path


def email_to_pdf(
    subject: str,
    sender: str,
    date: str,
    body_html: str,
    body_plain: str = "",
    output_path: Optional[Path] = None
) -> Path:
    """
    Convert an email to a PDF document.
    
    Args:
        subject: Email subject
        sender: Sender email/name
        date: Date string
        body_html: HTML body of the email
        body_plain: Plain text body (fallback if no HTML)
        output_path: Optional output path
        
    Returns:
        Path to the generated PDF
    """
    # Build email header
    header_html = f"""
    <div style="border-bottom: 2px solid #333; padding-bottom: 10px; margin-bottom: 20px;">
        <h2 style="margin: 0;">{subject}</h2>
        <p style="color: #666; margin: 5px 0;">
            <strong>From:</strong> {sender}<br>
            <strong>Date:</strong> {date}
        </p>
    </div>
    """
    
    # Use HTML body if available, otherwise plain text
    if body_html:
        content = body_html
    elif body_plain:
        # Convert plain text to HTML (preserve whitespace)
        content = f"<pre style='white-space: pre-wrap; font-family: inherit;'>{body_plain}</pre>"
    else:
        content = "<p><em>No content</em></p>"
    
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ 
                font-family: Arial, sans-serif; 
                padding: 30px;
                max-width: 800px;
                margin: 0 auto;
            }}
            img {{ max-width: 100%; }}
            table {{ border-collapse: collapse; width: 100%; }}
            td, th {{ border: 1px solid #ddd; padding: 8px; }}
        </style>
    </head>
    <body>
        {header_html}
        {content}
    </body>
    </html>
    """
    
    return html_to_pdf(full_html, output_path)
