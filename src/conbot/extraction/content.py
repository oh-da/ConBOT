"""
Content extraction from HTML.

Extracts main content and relevant snippets using:
- Trafilatura: Best-in-class article extraction (F1: 0.958)
- BeautifulSoup: Keyword-based snippet extraction
"""

import trafilatura
from bs4 import BeautifulSoup
import re
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class ContentExtractor:
    """
    Extract main content and keyword-relevant snippets from HTML.

    Uses two-stage extraction:
    1. Trafilatura for main content (removes navigation, ads, footers)
    2. BeautifulSoup for keyword-matched snippets

    Example:
        >>> extractor = ContentExtractor(keyword_groups={
        ...     'cfp': ['call for papers', 'deadline'],
        ...     'no_dates': ['upcoming', 'tba']
        ... })
        >>> main_content, snippets = extractor.extract(html)
        >>> filtered = extractor.get_filtered_content(html)  # For fingerprinting
    """

    def __init__(self, keyword_groups: Dict[str, List[str]]):
        """
        Initialize content extractor.

        Args:
            keyword_groups: Dictionary of keyword categories
                Example: {'cfp': ['call for papers', ...], 'no_dates': [...]}
        """
        self.keyword_groups = keyword_groups
        self._all_keywords = [
            kw.lower()
            for kwlist in keyword_groups.values()
            for kw in kwlist
        ]

    def extract(self, html: str) -> Tuple[str, List[str]]:
        """
        Extract main content and relevant snippets.

        Args:
            html: Raw HTML content

        Returns:
            Tuple of (main_content, relevant_snippets)
            main_content: Clean article text extracted by Trafilatura
            relevant_snippets: List of sentences containing keywords

        Example:
            >>> content, snippets = extractor.extract(html)
            >>> print(f"Main content: {len(content)} chars")
            >>> print(f"Found {len(snippets)} relevant snippets")
        """
        # Extract main content with Trafilatura (best performance)
        main_content = trafilatura.extract(
            html,
            include_comments=False,  # Skip comments
            include_tables=True,     # Keep tables (may contain dates)
            include_links=True,      # Keep link text
            no_fallback=False,       # Allow fallback extraction
            favor_precision=True,    # Prefer precision over recall
        )

        if not main_content:
            logger.warning("Trafilatura extraction returned empty, trying fallback")
            # Fallback: basic text extraction
            main_content = self._fallback_extraction(html)

        # Extract keyword-based snippets
        snippets = self._extract_snippets(html)

        logger.debug(
            f"Extracted {len(main_content)} chars main content, "
            f"{len(snippets)} snippets"
        )

        return main_content or "", snippets

    def get_filtered_content(self, html: str) -> str:
        """
        Get content with navigation/footer removed (for fingerprinting).

        This is used in tier-2 change detection to avoid false positives
        from dynamic navigation menus, footers, etc.

        Args:
            html: Raw HTML content

        Returns:
            Filtered text content with noise elements removed

        Example:
            >>> filtered = extractor.get_filtered_content(html)
            >>> hash = hashlib.sha256(filtered.encode()).hexdigest()
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Remove common noise elements
        for element in soup(['script', 'style', 'nav', 'footer', 'header',
                            'aside', 'iframe', 'noscript']):
            element.decompose()

        # Remove elements with common noise classes/IDs
        noise_patterns = [
            'menu', 'navigation', 'sidebar', 'footer', 'header',
            'cookie', 'banner', 'advertisement', 'ad-', 'social',
            'share', 'comment', 'related', 'recommend'
        ]

        for pattern in noise_patterns:
            # Remove by class
            for elem in soup.find_all(class_=re.compile(pattern, re.I)):
                elem.decompose()
            # Remove by ID
            for elem in soup.find_all(id=re.compile(pattern, re.I)):
                elem.decompose()

        # Get clean text
        text = soup.get_text(separator=' ', strip=True)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)

        return text.strip()

    def _extract_snippets(self, html: str) -> List[str]:
        """
        Extract text snippets containing keywords.

        Args:
            html: Raw HTML content

        Returns:
            List of unique sentences containing any keyword (max 50)
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Remove noise elements first
        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
            element.decompose()

        # Get all text
        text = soup.get_text(separator=' ', strip=True)

        # Split into sentences (simple heuristic)
        # Split on period, exclamation, question mark followed by space/newline
        sentences = re.split(r'[.!?]\s+', text)

        snippets = []
        seen = set()  # Deduplicate

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:  # Skip very short snippets
                continue

            sentence_lower = sentence.lower()

            # Check if contains any keyword
            if any(keyword in sentence_lower for keyword in self._all_keywords):
                # Deduplicate (case-insensitive)
                if sentence_lower not in seen:
                    snippets.append(sentence)
                    seen.add(sentence_lower)

                # Limit to avoid memory issues
                if len(snippets) >= 50:
                    break

        logger.debug(f"Extracted {len(snippets)} keyword-matched snippets")
        return snippets

    def _fallback_extraction(self, html: str) -> str:
        """
        Fallback extraction when Trafilatura fails.

        Uses simple BeautifulSoup text extraction.

        Args:
            html: Raw HTML content

        Returns:
            Basic text extraction
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Remove noise
        for element in soup(['script', 'style', 'nav', 'footer', 'header',
                            'aside', 'iframe', 'noscript']):
            element.decompose()

        # Try to find main content area
        main = soup.find('main') or soup.find('article') or soup.find('body')

        if main:
            text = main.get_text(separator=' ', strip=True)
        else:
            text = soup.get_text(separator=' ', strip=True)

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)

        logger.debug(f"Fallback extraction: {len(text)} chars")
        return text.strip()
