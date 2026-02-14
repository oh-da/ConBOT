"""
SQLAlchemy ORM models for SQLite database.

Defines tables:
- conferences_current: Current state of each conference
- conferences_audit: Append-only scan history
- scan_history: Performance and error tracking

All complex fields (lists, structs) are JSON-serialized as TEXT.
"""

from datetime import datetime
from typing import List, Optional
import json

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    CheckConstraint,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from ..models.conference import (
    ConferenceState,
    Deadline,
    TrackedLink,
    WatchMode,
    ChangeType,
)

Base = declarative_base()


# JSON serialization helpers
def serialize_deadlines(deadlines: List[Deadline]) -> str:
    """Serialize list of Deadline objects to JSON string."""
    if not deadlines:
        return "[]"
    return json.dumps([d.model_dump(mode='json') for d in deadlines])


def deserialize_deadlines(json_str: Optional[str]) -> List[Deadline]:
    """Deserialize JSON string to list of Deadline objects."""
    if not json_str or json_str == "[]":
        return []
    data = json.loads(json_str)
    return [Deadline(**d) for d in data]


def serialize_tracked_links(links: List[TrackedLink]) -> str:
    """Serialize list of TrackedLink objects to JSON string."""
    if not links:
        return "[]"
    return json.dumps([l.model_dump(mode='json') for l in links])


def deserialize_tracked_links(json_str: Optional[str]) -> List[TrackedLink]:
    """Deserialize JSON string to list of TrackedLink objects."""
    if not json_str or json_str == "[]":
        return []
    data = json.loads(json_str)
    return [TrackedLink(**d) for d in data]


class ConferenceCurrentTable(Base):
    """
    Current state of each monitored conference.

    Primary table storing the latest state for each conference.
    Updated via UPSERT (INSERT OR REPLACE) on each scan.
    """
    __tablename__ = "conferences_current"

    # Primary key
    conference_id = Column(String, primary_key=True, nullable=False)

    # Core fields
    url = Column(String, nullable=False)
    watch_mode = Column(
        String,
        nullable=False,
        default=WatchMode.MONTHLY.value
    )
    next_run_at = Column(DateTime, nullable=False)
    last_scan_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Fingerprints for change detection
    binary_hash = Column(String, nullable=True)
    filtered_hash = Column(String, nullable=True)
    simhash_signature = Column(Integer, nullable=True)

    # Extracted data (JSON serialized)
    current_deadlines = Column(Text, nullable=False, default="[]")  # JSON array
    current_summary = Column(Text, nullable=True)
    tracked_links = Column(Text, nullable=False, default="[]")  # JSON array

    # Metadata
    consecutive_no_change_count = Column(Integer, nullable=False, default=0)
    consecutive_error_count = Column(Integer, nullable=False, default=0)
    total_scans = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "watch_mode IN ('MONTHLY', 'BIWEEKLY', 'URGENT')",
            name="ck_watch_mode"
        ),
        Index("idx_conferences_next_run", "next_run_at"),
        Index("idx_conferences_watch_mode", "watch_mode"),
        Index("idx_conferences_active", "is_active"),
    )

    def to_conference_state(self) -> ConferenceState:
        """Convert database row to ConferenceState pydantic model."""
        return ConferenceState(
            conference_id=self.conference_id,
            url=self.url,
            watch_mode=WatchMode(self.watch_mode),
            next_run_at=self.next_run_at,
            last_scan_at=self.last_scan_at,
            binary_hash=self.binary_hash,
            filtered_hash=self.filtered_hash,
            simhash_signature=self.simhash_signature,
            current_deadlines=deserialize_deadlines(self.current_deadlines),
            current_summary=self.current_summary,
            tracked_links=deserialize_tracked_links(self.tracked_links),
            consecutive_no_change_count=self.consecutive_no_change_count,
            consecutive_error_count=self.consecutive_error_count,
            is_active=self.is_active,
            updated_at=self.updated_at,
        )

    @staticmethod
    def from_conference_state(state: ConferenceState) -> "ConferenceCurrentTable":
        """Create database row from ConferenceState pydantic model."""
        return ConferenceCurrentTable(
            conference_id=state.conference_id,
            url=str(state.url),
            watch_mode=state.watch_mode.value,
            next_run_at=state.next_run_at,
            last_scan_at=state.last_scan_at,
            binary_hash=state.binary_hash,
            filtered_hash=state.filtered_hash,
            simhash_signature=state.simhash_signature,
            current_deadlines=serialize_deadlines(state.current_deadlines),
            current_summary=state.current_summary,
            tracked_links=serialize_tracked_links(state.tracked_links),
            consecutive_no_change_count=state.consecutive_no_change_count,
            consecutive_error_count=state.consecutive_error_count,
            is_active=state.is_active,
            updated_at=state.updated_at,
        )


class ConferencesAuditTable(Base):
    """
    Append-only audit log of all scan results.

    Records every scan operation with full context for debugging
    and historical analysis.
    """
    __tablename__ = "conferences_audit"

    # Primary key
    audit_id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign key
    conference_id = Column(
        String,
        ForeignKey("conferences_current.conference_id"),
        nullable=False
    )

    # Scan metadata
    scan_timestamp = Column(DateTime, nullable=False)

    # Change detection
    change_detected = Column(Boolean, nullable=False)
    change_type = Column(String, nullable=True)  # NONE, BINARY, FILTERED, SEMANTIC
    hamming_distance = Column(Integer, nullable=True)

    # Extracted data (JSON serialized)
    deadlines_found = Column(Text, nullable=False, default="[]")  # JSON array
    summary = Column(Text, nullable=True)

    # State transition
    previous_watch_mode = Column(String, nullable=True)
    new_watch_mode = Column(String, nullable=True)
    transition_reason = Column(Text, nullable=True)

    # Performance
    fetch_method = Column(String, nullable=True)  # requests, playwright
    scan_duration_seconds = Column(Float, nullable=True)
    llm_api_called = Column(Boolean, nullable=False, default=False)
    email_sent = Column(Boolean, nullable=False, default=False)

    # Indexes
    __table_args__ = (
        Index("idx_audit_conference", "conference_id"),
        Index("idx_audit_timestamp", "scan_timestamp"),
    )


class ScanHistoryTable(Base):
    """
    Performance and error tracking for each scan operation.

    Lightweight table for monitoring scan health and troubleshooting.
    """
    __tablename__ = "scan_history"

    # Primary key
    run_id = Column(String, primary_key=True, nullable=False)  # UUID

    # Foreign key
    conference_id = Column(
        String,
        ForeignKey("conferences_current.conference_id"),
        nullable=False
    )

    # Scan info
    url = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)  # running, succeeded, failed

    # Performance
    fetch_method = Column(String, nullable=True)
    fetch_duration_ms = Column(Integer, nullable=True)

    # Results
    change_detected = Column(Boolean, nullable=True)
    deadlines_count = Column(Integer, nullable=True)
    email_type = Column(String, nullable=True)  # NO_CHANGE, CHANGE_NO_DATES, CHANGE_WITH_DATES

    # Errors
    error_details = Column(Text, nullable=True)

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_status"
        ),
        Index("idx_history_conference", "conference_id"),
        Index("idx_history_started", "started_at"),
        Index("idx_history_status", "status"),
    )


def create_tables(engine):
    """
    Create all tables in the database.

    Args:
        engine: SQLAlchemy engine

    Example:
        >>> from sqlalchemy import create_engine
        >>> engine = create_engine("sqlite:///~/.conbot/conbot.db")
        >>> create_tables(engine)
    """
    Base.metadata.create_all(engine)


def drop_tables(engine):
    """
    Drop all tables from the database.

    WARNING: This will delete all data!

    Args:
        engine: SQLAlchemy engine
    """
    Base.metadata.drop_all(engine)
