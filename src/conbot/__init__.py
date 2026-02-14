"""
ConBOT - Conference Tracking Bot

Automated system for monitoring academic/industry conference websites,
detecting changes, extracting submission deadlines, and sending email alerts.
"""

__version__ = "1.0.0"
__author__ = "Ohad"

from .models.conference import (
    WatchMode,
    DeadlineType,
    Deadline,
    TrackedLink,
    ConferenceState,
    ChangeType,
    ScanResult,
)

__all__ = [
    "WatchMode",
    "DeadlineType",
    "Deadline",
    "TrackedLink",
    "ConferenceState",
    "ChangeType",
    "ScanResult",
]
