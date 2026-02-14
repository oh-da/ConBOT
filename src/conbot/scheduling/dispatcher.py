"""
Schedule dispatcher for conference scanning.

Queries Delta tables to find conferences that are due for scanning
based on their next_run_at timestamp.
"""

from datetime import datetime
from typing import List
import logging
from ..models.conference import ConferenceState, WatchMode
from ..state.delta_store import DeltaStore
from .calculator import NextRunCalculator

logger = logging.getLogger(__name__)


class ScheduleDispatcher:
    """
    Dispatches scan jobs for conferences based on schedule.

    Workflow:
    1. Query conferences_current where next_run_at <= now
    2. Order by priority (URGENT first, then BIWEEKLY, then MONTHLY)
    3. Return list of conferences to scan
    4. After scan, update next_run_at based on new watch mode

    Example:
        >>> dispatcher = ScheduleDispatcher(delta_store)
        >>> conferences = dispatcher.get_conferences_to_scan()
        >>> for conf in conferences:
        ...     # Scan conference
        ...     dispatcher.update_next_run_after_scan(conf, new_mode)
    """

    def __init__(self, delta_store: DeltaStore):
        """
        Initialize dispatcher.

        Args:
            delta_store: Delta store instance for database operations
        """
        self.delta_store = delta_store
        self.calculator = NextRunCalculator()

    def get_conferences_to_scan(
        self,
        current_time: datetime = None
    ) -> List[ConferenceState]:
        """
        Get conferences that are due for scanning.

        Args:
            current_time: Current timestamp (default: now)

        Returns:
            List of ConferenceState objects, ordered by priority

        Example:
            >>> conferences = dispatcher.get_conferences_to_scan()
            >>> print(f"Found {len(conferences)} conferences to scan")
        """
        if current_time is None:
            current_time = datetime.now()

        logger.info(f"Querying conferences due for scan at {current_time}")

        try:
            conferences = self.delta_store.get_conferences_due_for_scan(current_time)

            # Log statistics
            by_mode = {}
            for conf in conferences:
                by_mode[conf.watch_mode] = by_mode.get(conf.watch_mode, 0) + 1

            logger.info(
                f"Found {len(conferences)} conferences to scan: "
                f"URGENT={by_mode.get(WatchMode.URGENT, 0)}, "
                f"BIWEEKLY={by_mode.get(WatchMode.BIWEEKLY, 0)}, "
                f"MONTHLY={by_mode.get(WatchMode.MONTHLY, 0)}"
            )

            return conferences

        except Exception as e:
            logger.error(f"Failed to get conferences to scan: {e}", exc_info=True)
            return []

    def update_next_run_after_scan(
        self,
        conference_id: str,
        url: str,
        new_watch_mode: WatchMode,
        scan_time: datetime = None
    ) -> datetime:
        """
        Update next_run_at after successful scan.

        Args:
            conference_id: Conference identifier
            url: Conference URL
            new_watch_mode: Watch mode after scan (may have changed)
            scan_time: Scan timestamp (default: now)

        Returns:
            Calculated next_run_at timestamp

        Example:
            >>> next_run = dispatcher.update_next_run_after_scan(
            ...     "uitp_summit",
            ...     "https://...",
            ...     WatchMode.URGENT
            ... )
            >>> print(f"Next scan: {next_run}")
        """
        if scan_time is None:
            scan_time = datetime.now()

        # Calculate next run based on new mode
        next_run = self.calculator.calculate_next_run(new_watch_mode, scan_time)

        # Update in database
        try:
            self.delta_store.update_conference(
                conference_id=conference_id,
                url=url,
                updates={
                    'watch_mode': new_watch_mode.value,
                    'next_run_at': next_run.isoformat(),
                    'last_scan_at': scan_time.isoformat(),
                }
            )

            logger.info(
                f"Updated {conference_id}: mode={new_watch_mode.value}, "
                f"next_run={next_run}"
            )

            return next_run

        except Exception as e:
            logger.error(
                f"Failed to update next_run for {conference_id}: {e}",
                exc_info=True
            )
            raise

    def get_scan_summary(self, current_time: datetime = None) -> dict:
        """
        Get summary of upcoming scans.

        Args:
            current_time: Current timestamp (default: now)

        Returns:
            Dictionary with scan statistics

        Example:
            >>> summary = dispatcher.get_scan_summary()
            >>> print(f"Overdue: {summary['overdue']}")
            >>> print(f"Today: {summary['today']}")
        """
        if current_time is None:
            current_time = datetime.now()

        # Query all active conferences
        query = f"""
        SELECT conference_id, url, watch_mode, next_run_at
        FROM {self.delta_store._table_name('conferences_current')}
        WHERE is_active = TRUE
        """

        try:
            df = self.delta_store.query(query)
            all_conferences = df.collect()

            summary = {
                'total_active': len(all_conferences),
                'overdue': 0,
                'today': 0,
                'this_week': 0,
                'by_mode': {
                    'URGENT': 0,
                    'BIWEEKLY': 0,
                    'MONTHLY': 0
                }
            }

            from datetime import timedelta

            for row in all_conferences:
                # Count by mode
                summary['by_mode'][row.watch_mode] += 1

                # Count by timing
                next_run = row.next_run_at
                if next_run <= current_time:
                    summary['overdue'] += 1
                elif next_run <= current_time + timedelta(days=1):
                    summary['today'] += 1
                elif next_run <= current_time + timedelta(days=7):
                    summary['this_week'] += 1

            logger.debug(f"Scan summary: {summary}")
            return summary

        except Exception as e:
            logger.error(f"Failed to get scan summary: {e}")
            return {'error': str(e)}
