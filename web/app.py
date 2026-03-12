"""
FastAPI Web Application for Finance Bot.
Provides a web interface for uploading receipts and viewing submission status.
Runs alongside the existing Slack bot.
"""
import asyncio
import logging
import os
import shutil
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config.settings import TEMP_DIR, DATABASE_URL, ClerkConfig
from web.models import (
    User, Submission, SubmissionStatus,
    get_engine, get_session_factory, init_db
)

logger = logging.getLogger(__name__)

# --- App setup ---
app = FastAPI(
    title="TPRobot",
    description="Receipt Processing & TPR Automation",
)

# Paths
WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"
UPLOAD_DIR = TEMP_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Database
engine = None
SessionFactory = None


@app.on_event("startup")
async def startup():
    """Initialize database on startup."""
    global engine, SessionFactory
    if DATABASE_URL:
        engine = init_db()
        SessionFactory = get_session_factory(engine)
        logger.info("Database initialized")
    else:
        logger.warning("DATABASE_URL not set — running without database")


def get_db():
    """Get a database session."""
    if SessionFactory is None:
        raise HTTPException(500, "Database not configured")
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


def get_or_create_user(session, andrew_id: str) -> User:
    """Get existing user or create a new one."""
    user = session.query(User).filter_by(andrew_id=andrew_id.lower().strip()).first()
    if not user:
        user = User(andrew_id=andrew_id.lower().strip())
        session.add(user)
        session.commit()
    return user


# ============================================================================
# Pages
# ============================================================================

def _clerk_ctx() -> dict:
    """Return Clerk template context variables."""
    return {
        "clerk_publishable_key": ClerkConfig.PUBLISHABLE_KEY,
        "clerk_frontend_api": ClerkConfig.FRONTEND_API,
    }


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Landing / upload page."""
    return templates.TemplateResponse("index.html", {"request": request, **_clerk_ctx()})


@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request, andrew_id: str = ""):
    """Submission status / history page."""
    submissions = []
    if andrew_id and SessionFactory:
        session = SessionFactory()
        try:
            user = session.query(User).filter_by(andrew_id=andrew_id.lower().strip()).first()
            if user:
                submissions = (
                    session.query(Submission)
                    .filter_by(user_id=user.id)
                    .order_by(Submission.created_at.desc())
                    .limit(50)
                    .all()
                )
        finally:
            session.close()
    
    return templates.TemplateResponse("status.html", {
        "request": request,
        "andrew_id": andrew_id,
        "submissions": submissions,
        **_clerk_ctx(),
    })


# ============================================================================
# API Endpoints
# ============================================================================

@app.post("/api/upload")
async def upload_receipt(
    receipts: List[UploadFile] = File(...),
    andrew_id: str = Form(...),
    justification: str = Form(...),
):
    """
    Upload one or more receipts for a single TPR submission.
    Runs VLM on each receipt, combines the amounts, and fills one TPR form.
    """
    if not receipts:
        raise HTTPException(400, "No files uploaded")
    
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
    
    # Validate Andrew ID
    andrew_id = andrew_id.strip().lower()
    if not andrew_id or len(andrew_id) < 2:
        raise HTTPException(400, "Please enter a valid Andrew ID")
    
    if not justification.strip():
        raise HTTPException(400, "Justification is required")
    
    # Validate and save all uploaded files
    file_paths: List[Path] = []
    original_filenames: List[str] = []
    
    for receipt in receipts:
        if not receipt.filename:
            continue
        ext = Path(receipt.filename).suffix.lower()
        if ext not in allowed:
            raise HTTPException(400, f"File type {ext} not supported. Use: {', '.join(allowed)}")
        
        file_id = uuid.uuid4().hex[:12]
        filename = f"{file_id}_{receipt.filename}"
        file_path = UPLOAD_DIR / filename
        
        with open(file_path, "wb") as f:
            shutil.copyfileobj(receipt.file, f)
        
        file_paths.append(file_path)
        original_filenames.append(receipt.filename)
    
    if not file_paths:
        raise HTTPException(400, "No valid files uploaded")
    
    logger.info(f"{len(file_paths)} receipt(s) uploaded by {andrew_id}: {original_filenames}")
    
    # Save to database
    submission_id = None
    if SessionFactory:
        session = SessionFactory()
        try:
            user = get_or_create_user(session, andrew_id)
            submission = Submission(
                user_id=user.id,
                original_filename=" + ".join(original_filenames),
                file_path=str(file_paths[0]),  # Primary file
                justification=justification.strip(),
                source="web",
                status=SubmissionStatus.PENDING.value,
            )
            session.add(submission)
            session.commit()
            submission_id = submission.id
        finally:
            session.close()
    
    # Trigger async processing with all file paths
    asyncio.create_task(_process_submission(file_paths, submission_id, justification))
    
    return RedirectResponse(
        url=f"/status?andrew_id={andrew_id}&submitted=1",
        status_code=303
    )


async def _process_submission(file_paths: List[Path], submission_id: Optional[int], justification: str):
    """
    Process one or more receipts through the full pipeline:
    1. VLM extraction on each receipt, combine amounts
    2. TPR form automation (Playwright)
    3. Google Drive upload (folder if multiple receipts)
    4. Budget & TPR tracking spreadsheet updates
    """
    demo_mode = os.getenv("DEMO_MODE", "false").lower() in ("true", "1", "yes")
    
    try:
        if submission_id and SessionFactory:
            session = SessionFactory()
            sub = session.query(Submission).get(submission_id)
            if sub:
                sub.status = SubmissionStatus.PROCESSING.value
                session.commit()
            session.close()
        
        # ---- Step 1: Extract receipt data from ALL files using VLM ----
        logger.info(f"[Submission {submission_id}] Step 1: VLM extraction on {len(file_paths)} receipt(s)...")
        from services.ocr_processor import extract_receipt_data
        
        all_extractions = []
        for i, fp in enumerate(file_paths):
            logger.info(f"[Submission {submission_id}] Extracting receipt {i+1}/{len(file_paths)}: {fp.name}")
            data = await asyncio.get_event_loop().run_in_executor(
                None, extract_receipt_data, fp
            )
            all_extractions.append(data)
            logger.info(f"  -> {data.vendor} ${data.amount} ({data.category})")
        
        # Use the first receipt as the primary (vendor, date, category, etc.)
        primary = all_extractions[0]
        
        # Sum up amounts from all receipts
        combined_amount = sum(d.amount for d in all_extractions)
        
        # Build a combined short description
        if len(all_extractions) > 1:
            vendors = list(dict.fromkeys(d.vendor for d in all_extractions))  # unique, ordered
            combined_desc = f"{' + '.join(vendors)} ({len(all_extractions)} receipts)"
        else:
            combined_desc = primary.short_description or ""
        
        # Create a combined ReceiptData with the summed amount and all file paths
        from models.receipt import ReceiptData
        receipt_data = ReceiptData(
            vendor=primary.vendor,
            date=primary.date,
            amount=combined_amount,
            raw_text="",
            file_path=file_paths[0],
            file_paths=list(file_paths),
            category=primary.category,
            short_description=combined_desc,
            is_food=any(d.is_food for d in all_extractions),
            is_travel=any(d.is_travel for d in all_extractions),
            confidence=min(d.confidence for d in all_extractions),
        )
        
        # Update database with combined extracted data
        if submission_id and SessionFactory:
            session = SessionFactory()
            sub = session.query(Submission).get(submission_id)
            if sub:
                sub.vendor = receipt_data.vendor
                sub.amount = receipt_data.amount
                sub.date = receipt_data.date
                sub.category = receipt_data.category or "Misc"
                sub.short_description = combined_desc
                sub.is_food = receipt_data.is_food
                sub.confidence = receipt_data.confidence
                sub.status = SubmissionStatus.PROCESSING.value  # Still processing
                session.commit()
            session.close()
        
        logger.info(
            f"[Submission {submission_id}] Combined: "
            f"{receipt_data.vendor} ${receipt_data.amount} ({receipt_data.category}) "
            f"from {len(all_extractions)} receipt(s)"
        )
        
        # ---- Step 2: TPR Form Automation ----
        logger.info(f"[Submission {submission_id}] Step 2: TPR form automation...")
        from services.tpr_automation import TPRFormAutomation, create_tpr_request
        
        tpr_request = await create_tpr_request(
            receipt=receipt_data,
            justification=justification,
        )
        
        tpr_automation = TPRFormAutomation(headless=False)
        tpr_number = await tpr_automation.process_tpr(tpr_request, demo_mode=demo_mode)
        
        if not tpr_number:
            logger.warning(f"[Submission {submission_id}] TPR automation completed but no TPR number returned")
        else:
            logger.info(f"[Submission {submission_id}] TPR number: {tpr_number}")
        
        # Update database with TPR number
        if submission_id and SessionFactory and tpr_number:
            session = SessionFactory()
            sub = session.query(Submission).get(submission_id)
            if sub:
                sub.tpr_number = tpr_number
                session.commit()
            session.close()
        
        # ---- Step 3: Google Drive Upload ----
        receipt_link = ""
        try:
            logger.info(f"[Submission {submission_id}] Step 3: Google Drive upload...")
            from utils.helpers import generate_receipt_filename
            
            if len(file_paths) == 1:
                # Single receipt: upload the file directly
                from services.google_drive import upload_receipt_to_drive
                receipt_filename = generate_receipt_filename(
                    receipt_data.vendor,
                    receipt_data.formatted_date,
                    receipt_data.amount,
                    department=receipt_data.category or "Misc",
                )
                receipt_link = await upload_receipt_to_drive(file_paths[0], receipt_filename)
            else:
                # Multiple receipts: create a folder and upload all files into it
                from services.google_drive import upload_receipts_to_folder
                folder_name = generate_receipt_filename(
                    receipt_data.vendor,
                    receipt_data.formatted_date,
                    receipt_data.amount,
                    department=receipt_data.category or "Misc",
                ).replace(".pdf", "")  # Remove extension for folder name
                receipt_link = await upload_receipts_to_folder(file_paths, folder_name)
            
            logger.info(f"[Submission {submission_id}] Uploaded to Drive: {receipt_link}")
            
            if submission_id and SessionFactory:
                session = SessionFactory()
                sub = session.query(Submission).get(submission_id)
                if sub:
                    sub.drive_link = receipt_link
                    session.commit()
                session.close()
        except Exception as drive_err:
            logger.warning(f"[Submission {submission_id}] Drive upload failed (non-fatal): {drive_err}")
        
        # ---- Step 4: Spreadsheet Updates ----
        try:
            logger.info(f"[Submission {submission_id}] Step 4: Updating spreadsheets...")
            from services.google_sheets import update_budget, update_tpr_tracking
            from models.receipt import Purchase
            
            purchase = Purchase(
                description=f"{receipt_data.vendor} - {justification[:50]}",
                amount=receipt_data.amount,
                vendor=receipt_data.vendor,
                receipt_link=receipt_link,
                tpr_number=tpr_number or "",
                department=receipt_data.category,
                date=receipt_data.date,
                justification=justification,
            )
            
            await update_budget(purchase)
            await update_tpr_tracking(purchase)
            logger.info(f"[Submission {submission_id}] Spreadsheets updated")
        except Exception as sheets_err:
            logger.warning(f"[Submission {submission_id}] Spreadsheet update failed (non-fatal): {sheets_err}")
        
        # ---- Done ----
        if submission_id and SessionFactory:
            session = SessionFactory()
            sub = session.query(Submission).get(submission_id)
            if sub:
                sub.status = SubmissionStatus.COMPLETE.value
                session.commit()
            session.close()
        
        logger.info(f"[Submission {submission_id}] ✅ Full pipeline complete!")
    
    except Exception as e:
        logger.error(f"[Submission {submission_id}] Pipeline failed: {e}", exc_info=True)
        if submission_id and SessionFactory:
            session = SessionFactory()
            sub = session.query(Submission).get(submission_id)
            if sub:
                sub.status = SubmissionStatus.FAILED.value
                sub.error_message = str(e)
                session.commit()
            session.close()


@app.get("/api/submissions/{andrew_id}")
async def get_submissions(andrew_id: str):
    """Get all submissions for a user as JSON."""
    if not SessionFactory:
        return JSONResponse({"submissions": [], "error": "Database not configured"})
    
    session = SessionFactory()
    try:
        user = session.query(User).filter_by(andrew_id=andrew_id.lower().strip()).first()
        if not user:
            return JSONResponse({"submissions": []})
        
        subs = (
            session.query(Submission)
            .filter_by(user_id=user.id)
            .order_by(Submission.created_at.desc())
            .limit(50)
            .all()
        )
        
        return JSONResponse({
            "submissions": [
                {
                    "id": s.id,
                    "vendor": s.vendor,
                    "amount": str(s.amount),
                    "date": s.formatted_date,
                    "category": s.category,
                    "justification": s.justification,
                    "status": s.status,
                    "status_emoji": s.status_emoji,
                    "tpr_number": s.tpr_number,
                    "created_at": s.created_at.isoformat() if s.created_at else "",
                }
                for s in subs
            ]
        })
    finally:
        session.close()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "finance-bot-web"}
