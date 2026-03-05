"""
Database models for the Finance Bot web application.
Uses SQLAlchemy with PostgreSQL.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime,
    Numeric, Text, Boolean, ForeignKey, Enum as SQLEnum
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker as async_sessionmaker
import enum

from config.settings import DATABASE_URL

Base = declarative_base()


class SubmissionStatus(str, enum.Enum):
    """Status of a receipt submission."""
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETE = "complete"
    FAILED = "failed"


class User(Base):
    """A user identified by their Andrew ID."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    andrew_id = Column(String(20), unique=True, nullable=False, index=True)
    display_name = Column(String(100), default="")
    email = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    submissions = relationship("Submission", back_populates="user")
    
    def __repr__(self):
        return f"<User {self.andrew_id}>"


class Submission(Base):
    """A receipt submission with extracted data and TPR status."""
    __tablename__ = "submissions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # File info
    original_filename = Column(String(255), default="receipt.pdf")
    file_path = Column(Text, nullable=False)
    drive_link = Column(Text, default="")
    
    # Extracted receipt data
    vendor = Column(String(200), default="")
    amount = Column(Numeric(10, 2), default=0)
    date = Column(DateTime, nullable=True)
    category = Column(String(50), default="Misc")
    short_description = Column(String(200), default="")
    is_food = Column(Boolean, default=False)
    confidence = Column(Integer, default=0)
    
    # Submission details
    justification = Column(Text, default="")
    department = Column(String(50), nullable=True)
    tpr_number = Column(String(50), default="")
    status = Column(String(20), default=SubmissionStatus.PENDING.value)
    error_message = Column(Text, default="")
    
    # Source: "web" or "slack"
    source = Column(String(10), default="web")
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    user = relationship("User", back_populates="submissions")
    
    def __repr__(self):
        return f"<Submission {self.id}: {self.vendor} ${self.amount}>"
    
    @property
    def status_emoji(self) -> str:
        """Return emoji for current status."""
        return {
            "pending": "⏳",
            "processing": "⚙️",
            "awaiting_review": "👀",
            "complete": "✅",
            "failed": "❌",
        }.get(self.status, "❓")
    
    @property
    def formatted_amount(self) -> str:
        return f"${self.amount:.2f}" if self.amount else "$0.00"
    
    @property
    def formatted_date(self) -> str:
        return self.date.strftime("%m/%d/%Y") if self.date else ""


# --- Database engine setup ---

def get_engine(url: str = None):
    """Create a SQLAlchemy engine."""
    db_url = url or DATABASE_URL
    if not db_url:
        raise ValueError("DATABASE_URL not configured in .env")
    return create_engine(db_url, echo=False)


def get_session_factory(engine=None):
    """Create a session factory."""
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine)


def init_db(engine=None):
    """Create all tables."""
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
    return engine
