"""
Pydantic models for conference tracking system.

Defines data structures for:
- ConferenceState: Current state of a conference being monitored
- ScanResult: Result of a single scan operation
- Deadline: Extracted deadline information
- TrackedLink: Discovered link being monitored
"""

from datetime import date, datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl


class WatchMode(str, Enum):
    """
    Watch mode determines scanning frequency.

    State transitions:
    - MONTHLY: Default mode, check every 30 days
    - BIWEEKLY: Content changed but no dates, check every 14 days
    - URGENT: Deadlines found, check daily
    """
    MONTHLY = "MONTHLY"
    BIWEEKLY = "BIWEEKLY"
    URGENT = "URGENT"


class DeadlineType(str, Enum):
    """Types of deadlines that can be extracted from conference websites."""
    ABSTRACT = "abstract"
    PAPER = "paper"
    REGISTRATION = "registration"
    CAMERA_READY = "camera-ready"
    GENERAL = "general"


class Deadline(BaseModel):
    """
    Represents an extracted conference deadline.

    Attributes:
        date: The deadline date
        type: Category of deadline (abstract, paper, etc.)
        confidence: Confidence score (0.0-1.0) from extraction algorithm
        source_text: Original text snippet where deadline was found
    """
    date: date
    type: DeadlineType
    confidence: float = Field(ge=0.0, le=1.0)
    source_text: str = Field(max_length=500)

    class Config:
        json_schema_extra = {
            "example": {
                "date": "2026-03-15",
                "type": "abstract",
                "confidence": 0.9,
                "source_text": "Abstract submission deadline: March 15, 2026"
            }
        }


class TrackedLink(BaseModel):
    """
    Represents a discovered link being monitored (for link discovery feature).

    Used for conferences like TRB and ITF where CFP pages have dynamic URLs.

    Attributes:
        url: The discovered URL
        score: Relevance score assigned by scoring algorithm
        first_seen: When this link was first discovered
    """
    url: HttpUrl
    score: float
    first_seen: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://example.com/annual-meeting/call-for-papers",
                "score": 8.5,
                "first_seen": "2026-02-14T10:30:00"
            }
        }


class ConferenceState(BaseModel):
    """
    Current state of a monitored conference.

    This is the primary state object persisted in conferences_current Delta table.
    Contains all information needed to track a conference between scans.

    Attributes:
        conference_id: Unique identifier for the conference
        url: Primary URL being monitored
        watch_mode: Current monitoring frequency (MONTHLY/BIWEEKLY/URGENT)
        next_run_at: When the next scan should occur
        last_scan_at: Timestamp of most recent scan

        binary_hash: SHA-256 hash of raw HTML (tier 1 change detection)
        filtered_hash: SHA-256 hash of filtered content (tier 2)
        simhash_signature: SimHash signature for semantic similarity (tier 3)

        current_deadlines: Most recently extracted deadlines
        current_summary: Most recent LLM-generated summary
        tracked_links: Discovered links being monitored (for link discovery)

        consecutive_no_change_count: Counter for scans with no changes
        consecutive_error_count: Counter for failed scans
        is_active: Whether monitoring is enabled for this conference
        updated_at: Last update timestamp
    """
    conference_id: str
    url: HttpUrl
    watch_mode: WatchMode
    next_run_at: datetime
    last_scan_at: Optional[datetime] = None

    # Fingerprints for change detection
    binary_hash: Optional[str] = None
    filtered_hash: Optional[str] = None
    simhash_signature: Optional[int] = None

    # Extracted data
    current_deadlines: List[Deadline] = Field(default_factory=list)
    current_summary: Optional[str] = None
    tracked_links: List[TrackedLink] = Field(default_factory=list)

    # Metadata
    consecutive_no_change_count: int = 0
    consecutive_error_count: int = 0
    is_active: bool = True
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        json_schema_extra = {
            "example": {
                "conference_id": "uitp_summit",
                "url": "https://www.uitpsummit.org/",
                "watch_mode": "MONTHLY",
                "next_run_at": "2026-03-15T09:00:00",
                "last_scan_at": "2026-02-14T10:30:00",
                "binary_hash": "a1b2c3...",
                "filtered_hash": "d4e5f6...",
                "simhash_signature": 123456789,
                "current_deadlines": [],
                "current_summary": None,
                "tracked_links": [],
                "consecutive_no_change_count": 3,
                "consecutive_error_count": 0,
                "is_active": True,
                "updated_at": "2026-02-14T10:30:00"
            }
        }


class ChangeType(str, Enum):
    """Type of change detected during scanning."""
    BINARY = "BINARY"          # Raw HTML changed
    FILTERED = "FILTERED"      # Filtered content changed
    SEMANTIC = "SEMANTIC"      # Semantic similarity changed (SimHash)
    NONE = "NONE"             # No change detected


class ScanResult(BaseModel):
    """
    Result of scanning a single conference URL.

    Contains all data extracted during a scan operation, including:
    - Fetched content
    - Change detection results
    - Extracted deadlines
    - Performance metrics

    Attributes:
        conference_id: Conference being scanned
        url: URL that was scanned
        scan_timestamp: When the scan occurred

        raw_html: Raw HTML content (optional, only if configured)
        main_content: Extracted main content (via Trafilatura)
        relevant_snippets: Keyword-matched text snippets

        change_detected: Whether any change was found
        change_type: Type of change (BINARY/FILTERED/SEMANTIC/NONE)
        hamming_distance: Hamming distance for SimHash comparison

        deadlines_found: List of extracted deadlines
        summary: LLM-generated summary (if change detected)

        fetch_method: How content was fetched (requests/playwright)
        scan_duration_seconds: Total scan time
        llm_api_called: Whether LLM was invoked
    """
    conference_id: str
    url: HttpUrl
    scan_timestamp: datetime

    # Fetched content
    raw_html: Optional[str] = None
    main_content: str
    relevant_snippets: List[str] = Field(default_factory=list)

    # Change detection
    change_detected: bool
    change_type: ChangeType
    hamming_distance: Optional[int] = None

    # Extracted data
    deadlines_found: List[Deadline] = Field(default_factory=list)
    summary: Optional[str] = None

    # Metadata
    fetch_method: str  # "requests" or "playwright"
    scan_duration_seconds: float
    llm_api_called: bool

    class Config:
        json_schema_extra = {
            "example": {
                "conference_id": "uitp_summit",
                "url": "https://www.uitpsummit.org/",
                "scan_timestamp": "2026-02-14T10:30:00",
                "raw_html": None,
                "main_content": "UITP Global Public Transport Summit...",
                "relevant_snippets": ["Call for papers now open", "Deadline March 15"],
                "change_detected": True,
                "change_type": "FILTERED",
                "hamming_distance": None,
                "deadlines_found": [
                    {
                        "date": "2026-03-15",
                        "type": "abstract",
                        "confidence": 0.9,
                        "source_text": "Abstract submission deadline: March 15, 2026"
                    }
                ],
                "summary": "Call for papers opened with abstract deadline March 15",
                "fetch_method": "requests",
                "scan_duration_seconds": 2.5,
                "llm_api_called": True
            }
        }
