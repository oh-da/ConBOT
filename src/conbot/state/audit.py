"""
Audit logging for conference scans.

Creates append-only records in conferences_audit table for
full traceability of all scans and state transitions.
"""

import uuid
from datetime import datetime
from typing import Optional
import logging
from .delta_store import DeltaStore
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

    Example:
        >>> audit = AuditLogger(delta_store)
        >>> audit.log_scan(state, scan_result, old_mode, new_mode, reason)
    """

    def __init__(self, delta_store: DeltaStore):
        """
        Initialize audit logger.

        Args:
            delta_store: Delta store instance for database operations
        """
        self.delta_store = delta_store

    def log_scan(
        self,
        conference_state: ConferenceState,
        scan_result: ScanResult,
        previous_watch_mode: Optional[WatchMode] = None,
        new_watch_mode: Optional[WatchMode] = None,
        transition_reason: Optional[str] = None,
        email_sent: bool = False
    ) -> str:
        """
        Log a scan operation to audit table.

        Args:
            conference_state: Current conference state
            scan_result: Result from scan
            previous_watch_mode: Mode before scan (None for first scan)
            new_watch_mode: Mode after scan
            transition_reason: Why mode changed (if applicable)
            email_sent: Whether email notification was sent

        Returns:
            Audit record ID (UUID)

        Example:
            >>> audit_id = audit.log_scan(
            ...     state,
            ...     result,
            ...     WatchMode.MONTHLY,
            ...     WatchMode.URGENT,
            ...     "DEADLINES_PUBLISHED",
            ...     email_sent=True
            ... )
        """
        audit_id = str(uuid.uuid4())

        # Prepare deadlines data
        deadlines_data = [
            {
                'date': dl.date.isoformat(),
                'type': dl.type.value,
                'confidence': dl.confidence,
                'source_text': dl.source_text,
            }
            for dl in scan_result.deadlines_found
        ]

        # Build audit record
        audit_data = {
            'audit_id': audit_id,
            'conference_id': scan_result.conference_id,
            'url': str(scan_result.url),
            'scan_timestamp': scan_result.scan_timestamp.isoformat(),

            # Change detection
            'change_detected': scan_result.change_detected,
            'change_type': scan_result.change_type.value,
            'previous_hash': conference_state.binary_hash,
            'new_hash': None,  # Would be set during processing
            'hamming_distance': scan_result.hamming_distance,

            # Extracted data
            'deadlines_found': deadlines_data,
            'summary': scan_result.summary,

            # State transition
            'previous_watch_mode': previous_watch_mode.value if previous_watch_mode else None,
            'new_watch_mode': new_watch_mode.value if new_watch_mode else conference_state.watch_mode.value,
            'transition_reason': transition_reason,

            # Performance and metadata
            'scan_duration_seconds': scan_result.scan_duration_seconds,
            'llm_api_called': scan_result.llm_api_called,
            'email_sent': email_sent,

            # Error handling
            'error_message': None,  # Would be set if scan failed
        }

        try:
            self.delta_store.insert_audit_record(audit_data)
            logger.info(
                f"Audit log created: {audit_id} for {scan_result.conference_id} "
                f"(change: {scan_result.change_detected}, deadlines: {len(deadlines_data)})"
            )
            return audit_id

        except Exception as e:
            logger.error(f"Failed to write audit log: {e}", exc_info=True)
            # Don't raise - audit logging failure shouldn't break main flow
            return audit_id

    def log_error(
        self,
        conference_id: str,
        url: str,
        error_message: str,
        previous_watch_mode: Optional[WatchMode] = None
    ) -> str:
        """
        Log a failed scan to audit table.

        Args:
            conference_id: Conference that failed
            url: URL that was attempted
            error_message: Error details
            previous_watch_mode: Mode before attempt

        Returns:
            Audit record ID

        Example:
            >>> audit.log_error(
            ...     "uitp_summit",
            ...     "https://...",
            ...     "Network timeout after 3 retries",
            ...     WatchMode.MONTHLY
            ... )
        """
        audit_id = str(uuid.uuid4())

        audit_data = {
            'audit_id': audit_id,
            'conference_id': conference_id,
            'url': url,
            'scan_timestamp': datetime.now().isoformat(),

            # No change info (scan failed)
            'change_detected': False,
            'change_type': 'NONE',
            'previous_hash': None,
            'new_hash': None,
            'hamming_distance': None,

            # No extracted data
            'deadlines_found': [],
            'summary': None,

            # State remained same
            'previous_watch_mode': previous_watch_mode.value if previous_watch_mode else None,
            'new_watch_mode': previous_watch_mode.value if previous_watch_mode else None,
            'transition_reason': 'SCAN_FAILED',

            # Performance
            'scan_duration_seconds': 0.0,
            'llm_api_called': False,
            'email_sent': False,

            # Error details
            'error_message': error_message,
        }

        try:
            self.delta_store.insert_audit_record(audit_data)
            logger.warning(f"Audit log (ERROR) created: {audit_id} for {conference_id}")
            return audit_id

        except Exception as e:
            logger.error(f"Failed to write error audit log: {e}", exc_info=True)
            return audit_id

    def get_recent_audits(
        self,
        conference_id: str,
        limit: int = 10
    ) -> list:
        """
        Retrieve recent audit records for a conference.

        Args:
            conference_id: Conference to query
            limit: Maximum number of records to return

        Returns:
            List of audit records (newest first)

        Example:
            >>> audits = audit.get_recent_audits("uitp_summit", limit=5)
            >>> for record in audits:
            ...     print(f"{record['scan_timestamp']}: {record['change_type']}")
        """
        query = f"""
        SELECT *
        FROM {self.delta_store._table_name('conferences_audit')}
        WHERE conference_id = '{conference_id}'
        ORDER BY scan_timestamp DESC
        LIMIT {limit}
        """

        try:
            df = self.delta_store.query(query)
            return df.collect()

        except Exception as e:
            logger.error(f"Failed to query audit history: {e}")
            return []
