"""
Date extraction and validation pipeline.

Extracts conference deadlines from unstructured text using:
- Hybrid date parsing (dateparser + dateutil)
- Regex pattern matching for deadline types
- Temporal validation (reasonable future dates only)
- Context-based filtering (exclude footers, copyright)
"""

import re
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple
import logging

# Try imports with fallbacks
try:
    import dateparser
    HAS_DATEPARSER = True
except ImportError:
    HAS_DATEPARSER = False
    logging.warning("dateparser not installed, using dateutil only")

try:
    from dateutil import parser as dateutil_parser
    HAS_DATEUTIL = True
except ImportError:
    HAS_DATEUTIL = False
    logging.warning("python-dateutil not installed")

from ..models.conference import Deadline, DeadlineType

logger = logging.getLogger(__name__)


class DateExtractor:
    """
    Extract and validate conference deadlines from text.

    Pipeline:
    1. Split text into sentences
    2. Filter out excluded contexts (footer, copyright)
    3. Parse dates using hybrid approach (dateutil → dateparser)
    4. Validate dates are in reasonable range
    5. Classify deadline type (abstract, paper, registration)
    6. Assign confidence score
    7. Deduplicate by (date, type)

    Example:
        >>> extractor = DateExtractor()
        >>> text = "Abstract submission deadline: March 15, 2026"
        >>> deadlines = extractor.extract_deadlines(text, [])
        >>> for dl in deadlines:
        ...     print(f"{dl.type}: {dl.date} (confidence: {dl.confidence})")
    """

    # Deadline type classification patterns
    TYPE_PATTERNS = {
        DeadlineType.ABSTRACT: r'\b(abstract|extended abstract)\s+(submission|deadline|due)',
        DeadlineType.PAPER: r'\b(paper|full paper|manuscript)\s+(submission|deadline|due)',
        DeadlineType.REGISTRATION: r'\b(registration|early bird|late registration)\s+(deadline|due|closes)',
        DeadlineType.CAMERA_READY: r'\b(camera[- ]?ready|final version|final submission)\s+(deadline|due)',
    }

    # Context patterns to exclude (footer, copyright, etc.)
    EXCLUDE_PATTERNS = [
        r'copyright\s+\d{4}',
        r'©\s*\d{4}',
        r'all rights reserved',
        r'last updated',
        r'page \d+ of \d+',
        r'powered by',
        r'website by',
        r'designed by',
    ]

    def __init__(
        self,
        min_date: Optional[date] = None,
        max_date: Optional[date] = None
    ):
        """
        Initialize date extractor.

        Args:
            min_date: Minimum valid date (default: today)
            max_date: Maximum valid date (default: today + 730 days)
        """
        self.min_date = min_date or date.today()
        self.max_date = max_date or (date.today() + timedelta(days=730))

        if not HAS_DATEUTIL and not HAS_DATEPARSER:
            raise ImportError(
                "Neither python-dateutil nor dateparser is installed. "
                "Install with: pip install python-dateutil dateparser"
            )

    def extract_deadlines(
        self,
        main_text: str,
        snippets: List[str]
    ) -> List[Deadline]:
        """
        Extract validated deadlines from main content and snippets.

        Args:
            main_text: Main article text
            snippets: Keyword-matched text snippets (higher relevance)

        Returns:
            List of Deadline objects, sorted by date

        Example:
            >>> deadlines = extractor.extract_deadlines(text, snippets)
            >>> if deadlines:
            ...     print(f"Found {len(deadlines)} deadlines")
            ...     print(f"Next deadline: {deadlines[0].date}")
        """
        deadlines = []

        # Process snippets first (higher relevance)
        for snippet in snippets:
            deadlines.extend(self._extract_from_text(snippet, is_snippet=True))

        # Process main content
        deadlines.extend(self._extract_from_text(main_text, is_snippet=False))

        # Deduplicate and sort
        unique_deadlines = self._deduplicate(deadlines)
        sorted_deadlines = sorted(unique_deadlines, key=lambda d: d.date)

        logger.info(f"Extracted {len(sorted_deadlines)} unique deadlines")
        return sorted_deadlines

    def _extract_from_text(
        self,
        text: str,
        is_snippet: bool = False
    ) -> List[Deadline]:
        """
        Extract deadlines from a single text block.

        Args:
            text: Text to extract from
            is_snippet: True if this is a snippet (boosts confidence)

        Returns:
            List of Deadline objects
        """
        deadlines = []

        # Split into sentences
        sentences = re.split(r'[.!?\n]+', text)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:  # Skip very short sentences
                continue

            # Skip excluded contexts
            if self._should_exclude(sentence):
                continue

            # Extract dates from sentence
            parsed_dates = self._parse_dates(sentence)

            for parsed_date, base_confidence in parsed_dates:
                if self._is_valid_date(parsed_date):
                    deadline_type = self._classify_type(sentence)

                    # Boost confidence for snippets
                    confidence = base_confidence
                    if is_snippet:
                        confidence = min(1.0, confidence + 0.1)

                    # Boost if explicit deadline keywords present
                    if re.search(r'\bdeadline\b', sentence, re.I):
                        confidence = min(1.0, confidence + 0.1)

                    deadlines.append(Deadline(
                        date=parsed_date,
                        type=deadline_type,
                        confidence=confidence,
                        source_text=sentence[:200]  # Limit length
                    ))

        return deadlines

    def _parse_dates(self, text: str) -> List[Tuple[date, float]]:
        """
        Parse dates from text using hybrid approach.

        Tries dateutil first (faster), falls back to dateparser.

        Args:
            text: Text containing potential dates

        Returns:
            List of (date, confidence) tuples
        """
        results = []

        # Try dateutil first (8x faster)
        if HAS_DATEUTIL:
            try:
                dt = dateutil_parser.parse(text, fuzzy=True, default=datetime.now())
                if dt:
                    results.append((dt.date(), 0.9))
                    return results  # Fast path - found a date
            except (ValueError, OverflowError):
                pass  # Try dateparser

        # Fallback to dateparser (more robust)
        if HAS_DATEPARSER:
            try:
                parsed = dateparser.parse(
                    text,
                    languages=['en'],
                    settings={
                        'PREFER_DATES_FROM': 'future',
                        'RELATIVE_BASE': datetime.now(),
                        'STRICT_PARSING': False,
                        'RETURN_AS_TIMEZONE_AWARE': False,
                    }
                )

                if parsed:
                    results.append((parsed.date(), 0.7))

            except Exception as e:
                logger.debug(f"dateparser failed: {e}")

        return results

    def _is_valid_date(self, d: date) -> bool:
        """
        Validate date is within reasonable conference timeframe.

        Args:
            d: Date to validate

        Returns:
            True if date is in range [min_date, max_date]
        """
        is_valid = self.min_date <= d <= self.max_date

        if not is_valid:
            logger.debug(
                f"Date {d} outside valid range "
                f"[{self.min_date}, {self.max_date}]"
            )

        return is_valid

    def _should_exclude(self, text: str) -> bool:
        """
        Check if text matches exclusion patterns.

        Args:
            text: Text to check

        Returns:
            True if text should be excluded (footer, copyright, etc.)
        """
        text_lower = text.lower()

        for pattern in self.EXCLUDE_PATTERNS:
            if re.search(pattern, text_lower):
                logger.debug(f"Excluding text matching pattern: {pattern}")
                return True

        return False

    def _classify_type(self, text: str) -> DeadlineType:
        """
        Classify deadline type from context.

        Args:
            text: Text containing deadline

        Returns:
            DeadlineType (ABSTRACT, PAPER, REGISTRATION, etc.)
        """
        text_lower = text.lower()

        # Check patterns in order of specificity
        for deadline_type, pattern in self.TYPE_PATTERNS.items():
            if re.search(pattern, text_lower):
                logger.debug(f"Classified as {deadline_type.value} (pattern: {pattern})")
                return deadline_type

        # Default to GENERAL if no specific match
        return DeadlineType.GENERAL

    def _deduplicate(self, deadlines: List[Deadline]) -> List[Deadline]:
        """
        Remove duplicate deadlines, keeping highest confidence.

        Duplicates are defined as same (date, type) pair.

        Args:
            deadlines: List of deadlines (may contain duplicates)

        Returns:
            Deduplicated list
        """
        # Group by (date, type)
        groups = {}

        for dl in deadlines:
            key = (dl.date, dl.type)
            if key not in groups or dl.confidence > groups[key].confidence:
                groups[key] = dl

        deduplicated = list(groups.values())
        logger.debug(
            f"Deduplicated {len(deadlines)} → {len(deduplicated)} deadlines"
        )

        return deduplicated
