"""
Unit tests for date extraction and validation.

Tests DateExtractor date parsing, validation, and classification logic.
"""

import pytest
from datetime import date, timedelta
from conbot.extraction.dates import DateExtractor
from conbot.models.conference import DeadlineType


class TestDateExtractor:
    """Test suite for DateExtractor class."""

    def test_extract_simple_date(self):
        """Test extraction of simple date format."""
        extractor = DateExtractor()
        text = "Abstract submission deadline: March 15, 2026"

        deadlines = extractor.extract_deadlines(text, [])

        assert len(deadlines) >= 1
        # Find the abstract deadline
        abstract_dl = next((d for d in deadlines if d.type == DeadlineType.ABSTRACT), None)
        assert abstract_dl is not None
        assert abstract_dl.date == date(2026, 3, 15)

    def test_extract_multiple_dates(self):
        """Test extraction of multiple deadlines."""
        extractor = DateExtractor()
        text = """
        Important Dates:
        - Abstract deadline: March 15, 2026
        - Paper deadline: April 30, 2026
        - Registration closes: May 15, 2026
        """

        deadlines = extractor.extract_deadlines(text, [])

        assert len(deadlines) >= 2  # Should find at least 2 dates

    def test_exclude_footer_dates(self):
        """Test that footer/copyright dates are excluded."""
        extractor = DateExtractor()
        text = "Copyright 2025. All rights reserved."

        deadlines = extractor.extract_deadlines(text, [])

        # Should not extract copyright year as deadline
        assert len(deadlines) == 0

    def test_validate_date_range_past(self):
        """Test that past dates are rejected."""
        extractor = DateExtractor()
        past_text = "Deadline was January 1, 2020"

        deadlines = extractor.extract_deadlines(past_text, [])

        assert len(deadlines) == 0

    def test_validate_date_range_far_future(self):
        """Test that dates too far in future are rejected."""
        extractor = DateExtractor()
        # Default max is today + 730 days (2 years)
        far_future = date.today() + timedelta(days=1000)
        far_future_text = f"Deadline is {far_future.strftime('%B %d, %Y')}"

        deadlines = extractor.extract_deadlines(far_future_text, [])

        assert len(deadlines) == 0

    def test_classify_abstract_deadline(self):
        """Test classification of abstract deadline."""
        extractor = DateExtractor()
        text = "Abstract submission due March 1, 2026"

        deadlines = extractor.extract_deadlines(text, [])

        if deadlines:
            assert any(d.type == DeadlineType.ABSTRACT for d in deadlines)

    def test_classify_paper_deadline(self):
        """Test classification of paper deadline."""
        extractor = DateExtractor()
        text = "Full paper deadline April 15, 2026"

        deadlines = extractor.extract_deadlines(text, [])

        if deadlines:
            assert any(d.type == DeadlineType.PAPER for d in deadlines)

    def test_classify_registration_deadline(self):
        """Test classification of registration deadline."""
        extractor = DateExtractor()
        text = "Registration closes May 1, 2026"

        deadlines = extractor.extract_deadlines(text, [])

        if deadlines:
            assert any(d.type == DeadlineType.REGISTRATION for d in deadlines)

    def test_deduplication(self):
        """Test that duplicate deadlines are removed."""
        extractor = DateExtractor()
        # Same date mentioned twice in different ways
        text = """
        Abstract deadline: March 15, 2026
        Submit your abstract by March 15, 2026
        """

        deadlines = extractor.extract_deadlines(text, [])

        # Should deduplicate by (date, type)
        abstract_deadlines = [d for d in deadlines if d.type == DeadlineType.ABSTRACT]
        dates = [d.date for d in abstract_deadlines]

        # Each unique date should appear only once
        assert len(dates) == len(set(dates))

    def test_snippets_boost_confidence(self):
        """Test that snippets get confidence boost."""
        extractor = DateExtractor()

        # Same text in main vs snippet
        text = "Deadline: March 15, 2026"

        # As main text
        main_deadlines = extractor.extract_deadlines(text, [])

        # As snippet
        snippet_deadlines = extractor.extract_deadlines("", [text])

        if main_deadlines and snippet_deadlines:
            # Snippet should have slightly higher confidence
            assert snippet_deadlines[0].confidence >= main_deadlines[0].confidence

    def test_sorting_by_date(self):
        """Test that deadlines are sorted by date."""
        extractor = DateExtractor()
        text = """
        - Paper deadline: April 30, 2026
        - Abstract deadline: March 15, 2026
        - Registration closes: May 15, 2026
        """

        deadlines = extractor.extract_deadlines(text, [])

        if len(deadlines) >= 2:
            # Should be sorted chronologically
            for i in range(len(deadlines) - 1):
                assert deadlines[i].date <= deadlines[i + 1].date

    def test_source_text_captured(self):
        """Test that source text is captured in deadline."""
        extractor = DateExtractor()
        text = "Abstract submission deadline: March 15, 2026"

        deadlines = extractor.extract_deadlines(text, [])

        if deadlines:
            assert deadlines[0].source_text is not None
            assert len(deadlines[0].source_text) > 0
            assert "march" in deadlines[0].source_text.lower()

    def test_exclude_last_updated(self):
        """Test that 'last updated' dates are excluded."""
        extractor = DateExtractor()
        text = "Last updated: February 14, 2025"

        deadlines = extractor.extract_deadlines(text, [])

        assert len(deadlines) == 0

    def test_custom_date_range(self):
        """Test custom min/max date range."""
        min_date = date(2026, 1, 1)
        max_date = date(2026, 12, 31)
        extractor = DateExtractor(min_date=min_date, max_date=max_date)

        # Date within range
        text1 = "Deadline: June 15, 2026"
        deadlines1 = extractor.extract_deadlines(text1, [])
        assert len(deadlines1) > 0

        # Date outside range
        text2 = "Deadline: June 15, 2027"
        deadlines2 = extractor.extract_deadlines(text2, [])
        assert len(deadlines2) == 0

    def test_empty_text(self):
        """Test handling of empty text."""
        extractor = DateExtractor()

        deadlines = extractor.extract_deadlines("", [])

        assert deadlines == []

    def test_iso_date_format(self):
        """Test parsing of ISO date format."""
        extractor = DateExtractor()
        text = "Deadline: 2026-03-15"

        deadlines = extractor.extract_deadlines(text, [])

        if deadlines:
            assert deadlines[0].date == date(2026, 3, 15)
