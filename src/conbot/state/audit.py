"""
Audit logging for conference scans.

Creates append-only records in the conferences_audit table and a
lightweight row per scan in scan_history, for full traceability of all
scans and state transitions.
"""

import uuid
from datetime import datetime
from typing import Optional
import logging
from ..models.conference import ConferenceState, ScanResult, WatchMode

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Audit logger for conference scanning operations.

    Creates immutable audit trail of:
    - All scans (successful and failed)
    - State transitions
    - Change detection results
    - Extracted deadlines

    Works with any store exposing ``insert_audit_record`` and
    ``insert_scan_history`` (SQLiteStore).

    Example:
        >>> audit = AuditLogger(store)
        >>> audit.log_scan(state, scan_result, WatchMode.MONTHLY, WatchMode.URGENT,
        ...                "DEADLINES_PUBLISHED", email_sent=True)
    """

    def __init__(self, delta_store):
        """
        Initialize audit logger.

        Args:
            delta_store: Store instance for database operations (kept under
                this name for backward compatibility)
        """
        self.delta_store = delta_store

    def log_scan(
        self,
        conference_state: ConferenceState,
        scan_result: ScanResult,
        previous_watch_mode: Optional[WatchMode] = None,
        new_watch_mode: Optional[WatchMode] = None,
        transition_reason: Optional[str] = None,
        email_sent: bool = False,
        email_type: Optional[str] = None
    ) -> str:
        """
        Log a successful scan to the audit and scan_history tables.

        Args:
            conference_state: Conference state after the scan
            scan_result: Result from scan
            previous_watch_mode: Mode before scan (None for first scan)
            new_watch_mode: Mode after scan
            transition_reason: Why mode changed (if applicable)
            email_sent: Whether email notification was sent
            email_type: NO_CHANGE / CHANGE_NO_DATES / CHANGE_WITH_DATES

        Returns:
            Run ID (UUID) shared with the scan_history row
        """
        run_id = str(uuid.uuid4())
        completed_at = datetime.now()

        audit_data = {
            'conference_id': scan_result.conference_id,
            'scan_timestamp': scan_result.scan_timestamp,
            'change_detected': scan_result.change_detected,
            'change_type': scan_result.change_type.value,
            'hamming_distance': scan_result.hamming_distance,
            'deadlines_found': scan_result.deadlines_found,
            'summary': scan_result.summary,
            'previous_watch_mode': previous_watch_mode.value if previous_watch_mode else None,
            'new_watch_mode': (
                new_watch_mode.value if new_watch_mode else conference_state.watch_mode.value
            ),
            'transition_reason': transition_reason,
            'fetch_method': scan_result.fetch_method,
            'scan_duration_seconds': scan_result.scan_duration_seconds,
            'llm_api_called': scan_result.llm_api_called,
            'email_sent': email_sent,
        }

        history_data = {
            'run_id': run_id,
            'conference_id': scan_result.conference_id,
            'url': str(scan_result.url),
            'started_at': scan_result.scan_timestamp,
            'completed_at': completed_at,
            'status': 'succeeded',
            'fetch_method': scan_result.fetch_method,
            'fetch_duration_ms': int(scan_result.scan_duration_seconds * 1000),
            'change_detected': scan_result.change_detected,
            'deadlines_count': len(scan_result.deadlines_found),
            'email_type': email_type,
        }

        try:
            self.delta_store.insert_audit_record(audit_data)
            self.delta_store.insert_scan_history(history_data)
            logger.info(
                f"Audit log created: {run_id} for {scan_result.conference_id} "
                f"(change: {scan_result.change_detected}, "
                f"deadlines: {len(scan_result.deadlines_found)})"
            )
        except Exception as e:
            # Audit failure shouldn't break the main flow
            logger.error(f"Failed to write audit log: {e}", exc_info=True)

        return run_id

    def log_error(
        self,
        conference_id: str,
        url: str,
        error_message: str,
        previous_watch_mode: Optional[WatchMode] = None,
        started_at: Optional[datetime] = None
    ) -> str:
        """
        Log a failed scan to the audit and scan_history tables.

        Args:
            conference_id: Conference that failed
            url: URL that was attempted
            error_message: Error details
            previous_watch_mode: Mode before attempt
            started_at: When the attempt started (default: now)

        Returns:
            Run ID (UUID)
        """
        run_id = str(uuid.uuid4())
        now = datetime.now()
        mode = previous_watch_mode.value if previous_watch_mode else None

        audit_data = {
            'conference_id': conference_id,
            'scan_timestamp': started_at or now,
            'change_detected': False,
            'change_type': 'NONE',
            'hamming_distance': None,
            'deadlines_found': [],
            'summary': None,
            'previous_watch_mode': mode,
            'new_watch_mode': mode,
            'transition_reason': f"SCAN_FAILED: {error_message}"[:1000],
            'fetch_method': None,
            'scan_duration_seconds': 0.0,
            'llm_api_called': False,
            'email_sent': False,
        }

        history_data = {
            'run_id': run_id,
            'conference_id': conference_id,
            'url': url,
            'started_at': started_at or now,
            'completed_at': now,
            'status': 'failed',
            'error_details': error_message,
        }

        try:
            self.delta_store.insert_audit_record(audit_data)
            self.delta_store.insert_scan_history(history_data)
            logger.warning(f"Audit log (ERROR) created: {run_id} for {conference_id}")
        except Exception as e:
            logger.error(f"Failed to write error audit log: {e}", exc_info=True)

        return run_id
