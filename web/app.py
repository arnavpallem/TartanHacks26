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
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config.settings import TEMP_DIR, DATABASE_URL
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

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Landing / upload page."""
    return templates.TemplateResponse("index.html", {"request": request})


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
    })


# ============================================================================
# API Endpoints
# ============================================================================

@app.post("/api/upload")
async def upload_receipt(
    receipt: UploadFile = File(...),
    andrew_id: str = Form(...),
    justification: str = Form(...),
):
    """
    Upload a receipt for TPR processing.
    Saves to database and triggers async VLM extraction.
    """
    # Validate file type
    if not receipt.filename:
        raise HTTPException(400, "No file uploaded")
    
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
    ext = Path(receipt.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"File type {ext} not supported. Use: {', '.join(allowed)}")
    
    # Validate Andrew ID
    andrew_id = andrew_id.strip().lower()
    if not andrew_id or len(andrew_id) < 2:
        raise HTTPException(400, "Please enter a valid Andrew ID")
    
    if not justification.strip():
        raise HTTPException(400, "Justification is required")
    
    # Save uploaded file
    file_id = uuid.uuid4().hex[:12]
    filename = f"{file_id}_{receipt.filename}"
    file_path = UPLOAD_DIR / filename
    
    with open(file_path, "wb") as f:
        shutil.copyfileobj(receipt.file, f)
    
    logger.info(f"Receipt uploaded: {filename} by {andrew_id}")
    
    # Save to database
    submission_id = None
    if SessionFactory:
        session = SessionFactory()
        try:
            user = get_or_create_user(session, andrew_id)
            submission = Submission(
                user_id=user.id,
                original_filename=receipt.filename,
                file_path=str(file_path),
                justification=justification.strip(),
                source="web",
                status=SubmissionStatus.PENDING.value,
            )
            session.add(submission)
            session.commit()
            submission_id = submission.id
        finally:
            session.close()
    
    # Trigger async processing
    asyncio.create_task(_process_submission(file_path, submission_id, justification))
    
    return RedirectResponse(
        url=f"/status?andrew_id={andrew_id}&submitted=1",
        status_code=303
    )


async def _process_submission(file_path: Path, submission_id: Optional[int], justification: str):
    """
    Process a receipt submission in the background.
    Runs VLM extraction and updates database — TPR submission handled separately.
    """
    try:
        if submission_id and SessionFactory:
            session = SessionFactory()
            sub = session.query(Submission).get(submission_id)
            if sub:
                sub.status = SubmissionStatus.PROCESSING.value
                session.commit()
            session.close()
        
        # Extract receipt data using VLM (Ollama → Gemini)
        from services.ocr_processor import extract_receipt_data
        receipt_data = await asyncio.get_event_loop().run_in_executor(
            None, extract_receipt_data, file_path
        )
        
        # Update database with extracted data
        if submission_id and SessionFactory:
            session = SessionFactory()
            sub = session.query(Submission).get(submission_id)
            if sub:
                sub.vendor = receipt_data.vendor
                sub.amount = receipt_data.amount
                sub.date = receipt_data.date
                sub.category = receipt_data.category or "Misc"
                sub.short_description = receipt_data.short_description or ""
                sub.is_food = receipt_data.is_food
                sub.confidence = receipt_data.confidence
                sub.status = SubmissionStatus.AWAITING_REVIEW.value
                session.commit()
            session.close()
        
        logger.info(f"Submission {submission_id} processed: {receipt_data.vendor} ${receipt_data.amount}")
    
    except Exception as e:
        logger.error(f"Processing failed for submission {submission_id}: {e}")
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
