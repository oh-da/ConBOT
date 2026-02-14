"""
Next run time calculator for conference scanning.

Calculates next_run_at timestamp based on watch mode:
- MONTHLY: +30 days
- BIWEEKLY: +14 days
- URGENT: +1 day
"""

from datetime import datetime, timedelta
from ..models.conference import WatchMode
import logging

logger = logging.getLogger(__name__)


class NextRunCalculator:
    """
    Calculate next_run_at timestamp based on watch mode.

    Example:
        >>> calculator = NextRunCalculator()
        >>> next_run = calculator.calculate_next_run(WatchMode.MONTHLY)
        >>> print(f"Next run: {next_run}")
        Next run: 2026-03-16 09:00:00
    """

    # Schedule intervals by mode
    INTERVALS = {
        WatchMode.MONTHLY: timedelta(days=30),
        WatchMode.BIWEEKLY: timedelta(days=14),
        WatchMode.URGENT: timedelta(days=1),
    }

    @classmethod
    def calculate_next_run(
        cls,
        watch_mode: WatchMode,
        base_time: datetime = None,
        hour: int = 9,  # Default: 9 AM
        minute: int = 0
    ) -> datetime:
        """
        Calculate next run timestamp.

        Args:
            watch_mode: Current watch mode
            base_time: Base timestamp (default: now)
            hour: Hour of day for scheduled run (0-23)
            minute: Minute of hour for scheduled run (0-59)

        Returns:
            Next scheduled run timestamp

        Example:
            >>> next_run = calculator.calculate_next_run(
            ...     WatchMode.BIWEEKLY,
            ...     datetime(2026, 2, 14, 10, 0)
            ... )
            >>> # Returns: 2026-02-28 09:00:00
        """
        if base_time is None:
            base_time = datetime.now()

        # Get interval for this mode
        interval = cls.INTERVALS[watch_mode]

        # Calculate next run
        next_run = base_time + interval

        # Set to specific time of day (e.g., 9:00 AM)
        next_run = next_run.replace(hour=hour, minute=minute, second=0, microsecond=0)

        logger.debug(
            f"Next run calculated: {watch_mode.value} mode, "
            f"interval={interval.days} days, next_run={next_run}"
        )

        return next_run

    @classmethod
    def get_interval_days(cls, watch_mode: WatchMode) -> int:
        """
        Get interval in days for a watch mode.

        Args:
            watch_mode: Watch mode to query

        Returns:
            Number of days between scans

        Example:
            >>> days = NextRunCalculator.get_interval_days(WatchMode.MONTHLY)
            >>> print(f"Scan every {days} days")
            Scan every 30 days
        """
        return cls.INTERVALS[watch_mode].days

    @classmethod
    def is_overdue(cls, next_run_at: datetime, current_time: datetime = None) -> bool:
        """
        Check if a scan is overdue.

        Args:
            next_run_at: Scheduled run time
            current_time: Current time (default: now)

        Returns:
            True if scan should have run already

        Example:
            >>> is_overdue = calculator.is_overdue(
            ...     datetime(2026, 2, 10),
            ...     datetime(2026, 2, 14)
            ... )
            >>> # Returns: True (4 days overdue)
        """
        if current_time is None:
            current_time = datetime.now()

        overdue = current_time >= next_run_at

        if overdue:
            delay = current_time - next_run_at
            logger.debug(f"Scan overdue by {delay}")

        return overdue

    @classmethod
    def get_time_until_next_run(cls, next_run_at: datetime, current_time: datetime = None) -> timedelta:
        """
        Get time remaining until next run.

        Args:
            next_run_at: Scheduled run time
            current_time: Current time (default: now)

        Returns:
            Time delta (negative if overdue)

        Example:
            >>> remaining = calculator.get_time_until_next_run(next_run_at)
            >>> if remaining.total_seconds() < 0:
            ...     print("Overdue!")
            ... else:
            ...     print(f"Runs in {remaining}")
        """
        if current_time is None:
            current_time = datetime.now()

        return next_run_at - current_time
