"""
State machine for watch mode transitions.

Implements the state transition logic:
- MONTHLY → BIWEEKLY (change detected, no dates)
- BIWEEKLY → URGENT (dates found)
- MONTHLY → URGENT (dates found directly)
- URGENT → URGENT (stay in urgent once dates found)
"""

from typing import Tuple
from ..models.conference import WatchMode, ScanResult
import logging

logger = logging.getLogger(__name__)


class StateTransitionEngine:
    """
    Manages watch mode transitions based on scan results.

    Transition Rules:
    ┌─────────┬───────────────┬───────────────┬─────────────┐
    │ Current │ Change?       │ Dates Found?  │ New Mode    │
    ├─────────┼───────────────┼───────────────┼─────────────┤
    │ MONTHLY │ No            │ -             │ MONTHLY     │
    │ MONTHLY │ Yes           │ No            │ BIWEEKLY    │
    │ MONTHLY │ Yes           │ Yes           │ URGENT      │
    │ BIWEEKLY│ No            │ -             │ BIWEEKLY    │
    │ BIWEEKLY│ Yes           │ Yes           │ URGENT      │
    │ URGENT  │ Any           │ Any           │ URGENT      │
    └─────────┴───────────────┴───────────────┴─────────────┘

    Example:
        >>> engine = StateTransitionEngine()
        >>> new_mode, reason = engine.determine_new_mode(
        ...     current_mode=WatchMode.MONTHLY,
        ...     scan_result=result_with_dates
        ... )
        >>> print(f"Transition: MONTHLY → {new_mode} ({reason})")
    """

    @staticmethod
    def determine_new_mode(
        current_mode: WatchMode,
        scan_result: ScanResult
    ) -> Tuple[WatchMode, str]:
        """
        Determine new watch mode based on current state and scan result.

        Args:
            current_mode: Current watch mode (MONTHLY, BIWEEKLY, URGENT)
            scan_result: Result from most recent scan

        Returns:
            Tuple of (new_mode, transition_reason)
            transition_reason: Human-readable explanation

        Example:
            >>> mode, reason = engine.determine_new_mode(
            ...     WatchMode.MONTHLY,
            ...     scan_result
            ... )
            >>> if mode != current_mode:
            ...     print(f"Mode changed: {reason}")
        """
        # URGENT mode is sticky - once urgent, stay urgent
        if current_mode == WatchMode.URGENT:
            logger.debug("Already in URGENT mode, staying URGENT")
            return WatchMode.URGENT, "ALREADY_URGENT"

        # No change detected - keep current mode
        if not scan_result.change_detected:
            logger.debug(f"No change detected, staying in {current_mode.value}")
            return current_mode, "NO_CHANGE"

        # Dates found - always go to URGENT
        if scan_result.deadlines_found and len(scan_result.deadlines_found) > 0:
            logger.info(
                f"Deadlines found ({len(scan_result.deadlines_found)}), "
                f"transitioning to URGENT"
            )
            return WatchMode.URGENT, "DEADLINES_PUBLISHED"

        # Change detected but no dates
        if current_mode == WatchMode.MONTHLY:
            logger.info("Content changed but no dates, transitioning to BIWEEKLY")
            return WatchMode.BIWEEKLY, "CONTENT_UPDATED_NO_DATES"

        elif current_mode == WatchMode.BIWEEKLY:
            logger.debug("Still BIWEEKLY, content changed but no dates")
            return WatchMode.BIWEEKLY, "CONTINUE_MONITORING"

        # Should not reach here, but return current mode as fallback
        logger.warning(f"Unexpected state: {current_mode}, returning same mode")
        return current_mode, "UNKNOWN_TRANSITION"

    @staticmethod
    def should_send_email(
        current_mode: WatchMode,
        new_mode: WatchMode,
        scan_result: ScanResult
    ) -> Tuple[bool, str]:
        """
        Determine if email should be sent and which type.

        According to spec: Always send email after each scan.

        Args:
            current_mode: Mode before scan
            new_mode: Mode after scan
            scan_result: Scan result

        Returns:
            Tuple of (should_send, email_type)
            email_type: "NO_CHANGE" | "CHANGE_NO_DATES" | "CHANGE_WITH_DATES"

        Example:
            >>> should_send, email_type = engine.should_send_email(
            ...     WatchMode.MONTHLY,
            ...     WatchMode.URGENT,
            ...     scan_result
            ... )
            >>> if should_send:
            ...     print(f"Send {email_type} email")
        """
        # Always send email (per requirements)
        # Email type depends on scan result

        if not scan_result.change_detected:
            return True, "NO_CHANGE"

        if scan_result.deadlines_found and len(scan_result.deadlines_found) > 0:
            return True, "CHANGE_WITH_DATES"

        return True, "CHANGE_NO_DATES"

    @staticmethod
    def get_transition_summary(
        old_mode: WatchMode,
        new_mode: WatchMode,
        reason: str,
        scan_result: ScanResult
    ) -> str:
        """
        Generate human-readable transition summary for logging/audit.

        Args:
            old_mode: Previous watch mode
            new_mode: New watch mode
            reason: Transition reason code
            scan_result: Scan result

        Returns:
            Human-readable summary string

        Example:
            >>> summary = engine.get_transition_summary(
            ...     WatchMode.MONTHLY,
            ...     WatchMode.URGENT,
            ...     "DEADLINES_PUBLISHED",
            ...     scan_result
            ... )
            >>> print(summary)
            Transition: MONTHLY → URGENT
            Reason: DEADLINES_PUBLISHED
            Change detected: True (FILTERED)
            Deadlines found: 3
        """
        lines = [
            f"Transition: {old_mode.value} → {new_mode.value}",
            f"Reason: {reason}",
            f"Change detected: {scan_result.change_detected} ({scan_result.change_type.value})",
            f"Deadlines found: {len(scan_result.deadlines_found)}",
        ]

        if scan_result.deadlines_found:
            lines.append("Deadline dates:")
            for dl in scan_result.deadlines_found:
                lines.append(f"  - {dl.date} ({dl.type.value})")

        return "\n".join(lines)
