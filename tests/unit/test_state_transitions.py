"""
Unit tests for state machine transitions.

Tests StateTransitionEngine logic for all transition scenarios.
"""

import pytest
from datetime import datetime
from conbot.state.transitions import StateTransitionEngine
from conbot.models.conference import WatchMode, ScanResult, ChangeType


class TestStateTransitions:
    """Test suite for StateTransitionEngine."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = StateTransitionEngine()

    def _make_scan_result(
        self,
        change_detected: bool = False,
        deadlines_count: int = 0
    ) -> ScanResult:
        """Helper to create ScanResult for testing."""
        from conbot.models.conference import Deadline, DeadlineType
        from datetime import date

        deadlines = []
        if deadlines_count > 0:
            for i in range(deadlines_count):
                deadlines.append(Deadline(
                    date=date(2026, 3, 15 + i),
                    type=DeadlineType.ABSTRACT,
                    confidence=0.9,
                    source_text=f"Deadline {i+1}"
                ))

        return ScanResult(
            conference_id="test_conf",
            url="https://test.com",
            scan_timestamp=datetime.now(),
            main_content="Test content",
            relevant_snippets=[],
            change_detected=change_detected,
            change_type=ChangeType.FILTERED if change_detected else ChangeType.NONE,
            hamming_distance=None,
            deadlines_found=deadlines,
            summary="Test summary" if change_detected else None,
            fetch_method="requests",
            scan_duration_seconds=1.0,
            llm_api_called=change_detected
        )

    def test_monthly_to_monthly_no_change(self):
        """Test MONTHLY stays MONTHLY when no change."""
        result = self._make_scan_result(change_detected=False)
        new_mode, reason = self.engine.determine_new_mode(WatchMode.MONTHLY, result)

        assert new_mode == WatchMode.MONTHLY
        assert reason == "NO_CHANGE"

    def test_monthly_to_biweekly_change_no_dates(self):
        """Test MONTHLY → BIWEEKLY when change but no dates."""
        result = self._make_scan_result(change_detected=True, deadlines_count=0)
        new_mode, reason = self.engine.determine_new_mode(WatchMode.MONTHLY, result)

        assert new_mode == WatchMode.BIWEEKLY
        assert reason == "CONTENT_UPDATED_NO_DATES"

    def test_monthly_to_urgent_with_dates(self):
        """Test MONTHLY → URGENT when dates found."""
        result = self._make_scan_result(change_detected=True, deadlines_count=2)
        new_mode, reason = self.engine.determine_new_mode(WatchMode.MONTHLY, result)

        assert new_mode == WatchMode.URGENT
        assert reason == "DEADLINES_PUBLISHED"

    def test_biweekly_to_biweekly_no_change(self):
        """Test BIWEEKLY stays BIWEEKLY when no change."""
        result = self._make_scan_result(change_detected=False)
        new_mode, reason = self.engine.determine_new_mode(WatchMode.BIWEEKLY, result)

        assert new_mode == WatchMode.BIWEEKLY
        assert reason == "NO_CHANGE"

    def test_biweekly_to_biweekly_change_no_dates(self):
        """Test BIWEEKLY stays BIWEEKLY when change but no dates."""
        result = self._make_scan_result(change_detected=True, deadlines_count=0)
        new_mode, reason = self.engine.determine_new_mode(WatchMode.BIWEEKLY, result)

        assert new_mode == WatchMode.BIWEEKLY
        assert reason == "CONTINUE_MONITORING"

    def test_biweekly_to_urgent_with_dates(self):
        """Test BIWEEKLY → URGENT when dates found."""
        result = self._make_scan_result(change_detected=True, deadlines_count=3)
        new_mode, reason = self.engine.determine_new_mode(WatchMode.BIWEEKLY, result)

        assert new_mode == WatchMode.URGENT
        assert reason == "DEADLINES_PUBLISHED"

    def test_urgent_stays_urgent(self):
        """Test URGENT stays URGENT (sticky state)."""
        # No change
        result_no_change = self._make_scan_result(change_detected=False)
        new_mode, reason = self.engine.determine_new_mode(WatchMode.URGENT, result_no_change)
        assert new_mode == WatchMode.URGENT
        assert reason == "ALREADY_URGENT"

        # Change without dates
        result_change = self._make_scan_result(change_detected=True, deadlines_count=0)
        new_mode, reason = self.engine.determine_new_mode(WatchMode.URGENT, result_change)
        assert new_mode == WatchMode.URGENT

        # Change with dates
        result_dates = self._make_scan_result(change_detected=True, deadlines_count=1)
        new_mode, reason = self.engine.determine_new_mode(WatchMode.URGENT, result_dates)
        assert new_mode == WatchMode.URGENT

    def test_should_send_email_no_change(self):
        """Test email decision for no change."""
        result = self._make_scan_result(change_detected=False)
        should_send, email_type = self.engine.should_send_email(
            WatchMode.MONTHLY,
            WatchMode.MONTHLY,
            result
        )

        assert should_send is True
        assert email_type == "NO_CHANGE"

    def test_should_send_email_change_no_dates(self):
        """Test email decision for change without dates."""
        result = self._make_scan_result(change_detected=True, deadlines_count=0)
        should_send, email_type = self.engine.should_send_email(
            WatchMode.MONTHLY,
            WatchMode.BIWEEKLY,
            result
        )

        assert should_send is True
        assert email_type == "CHANGE_NO_DATES"

    def test_should_send_email_with_dates(self):
        """Test email decision for dates found."""
        result = self._make_scan_result(change_detected=True, deadlines_count=2)
        should_send, email_type = self.engine.should_send_email(
            WatchMode.MONTHLY,
            WatchMode.URGENT,
            result
        )

        assert should_send is True
        assert email_type == "CHANGE_WITH_DATES"

    def test_get_transition_summary(self):
        """Test transition summary generation."""
        result = self._make_scan_result(change_detected=True, deadlines_count=1)
        summary = self.engine.get_transition_summary(
            old_mode=WatchMode.MONTHLY,
            new_mode=WatchMode.URGENT,
            reason="DEADLINES_PUBLISHED",
            scan_result=result
        )

        assert "MONTHLY → URGENT" in summary
        assert "DEADLINES_PUBLISHED" in summary
        assert "Deadlines found: 1" in summary
        assert "2026-03-15" in summary
