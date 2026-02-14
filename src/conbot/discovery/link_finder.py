"""
Link discovery for conferences with dynamic CFP URLs.

Parses seed pages to discover relevant links for conferences like
TRB and ITF where CFP URLs change annually.
"""

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import Dict, List, Set
import re
import logging
from .scoring import LinkScorer
from ..models.conference import TrackedLink
from datetime import datetime

logger = logging.getLogger(__name__)


class LinkDiscovery:
    """
    Discover and track relevant links for conferences.

    Used for conferences where CFP pages have dynamic/changing URLs
    each year (e.g., TRB, ITF).

    Process:
    1. Fetch seed page(s)
    2. Extract all links
    3. Filter by include/exclude patterns
    4. Score each link for relevance
    5. Return top N links to track

    Example:
        >>> discovery = LinkDiscovery(
        ...     seed_url="https://example.com/conferences",
        ...     config={
        ...         'include_if_url_contains': ['call', 'paper'],
        ...         'include_if_anchor_contains': ['submit'],
        ...         'max_discovered_urls': 10
        ...     }
        ... )
        >>> tracked = discovery.discover_links(html)
        >>> for link in tracked:
        ...     print(f"{link['score']}: {link['url']}")
    """

    def __init__(
        self,
        seed_url: str,
        config: Dict,
        custom_keywords: List[str] = None
    ):
        """
        Initialize link discovery.

        Args:
            seed_url: Starting page URL
            config: Discovery configuration with filters
            custom_keywords: Conference-specific keywords for scoring
        """
        self.seed_url = seed_url
        self.config = config
        self.scorer = LinkScorer(custom_keywords=custom_keywords or [])

        # Parse seed URL for domain filtering
        parsed = urlparse(seed_url)
        self.seed_domain = parsed.netloc

    def discover_links(self, html: str) -> List[TrackedLink]:
        """
        Parse HTML and discover relevant links.

        Args:
            html: HTML content from seed page

        Returns:
            List of TrackedLink objects (top N by score)

        Example:
            >>> links = discovery.discover_links(html)
            >>> print(f"Found {len(links)} relevant links")
        """
        soup = BeautifulSoup(html, 'html.parser')
        candidates = []
        seen_urls: Set[str] = set()

        # Extract all links
        for link_elem in soup.find_all('a', href=True):
            url = urljoin(self.seed_url, link_elem['href'])

            # Normalize URL (remove fragments, query params)
            normalized = self._normalize_url(url)

            if not normalized or normalized in seen_urls:
                continue

            seen_urls.add(normalized)

            # Apply filters
            if not self._passes_filters(normalized, link_elem):
                continue

            # Extract link metadata
            link_text = link_elem.get_text(strip=True)
            title = link_elem.get('title', '')
            context = self._get_context(link_elem)

            # Score link
            score = self.scorer.score_link(
                url=normalized,
                link_text=link_text,
                title=title,
                context=context
            )

            if score > 0:
                candidates.append({
                    'url': normalized,
                    'score': score,
                    'text': link_text,
                    'title': title,
                    'context': context,
                })

        # Sort by score and return top N
        max_urls = self.config.get('max_discovered_urls', 10)
        candidates.sort(key=lambda x: x['score'], reverse=True)
        top_candidates = candidates[:max_urls]

        # Convert to TrackedLink objects
        tracked_links = [
            TrackedLink(
                url=link['url'],
                score=link['score'],
                first_seen=datetime.now()
            )
            for link in top_candidates
        ]

        logger.info(
            f"Discovered {len(tracked_links)} links from {len(seen_urls)} candidates "
            f"(top score: {tracked_links[0].score if tracked_links else 0})"
        )

        return tracked_links

    def _normalize_url(self, url: str) -> str:
        """
        Normalize URL for deduplication.

        Removes:
        - Fragment (#section)
        - Query parameters (?page=1)
        - Trailing slashes

        Args:
            url: Raw URL

        Returns:
            Normalized URL or empty string if invalid
        """
        try:
            parsed = urlparse(url)

            # Skip non-HTTP(S) URLs
            if parsed.scheme not in ['http', 'https']:
                return ""

            # Rebuild without query/fragment
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

            # Remove trailing slash
            if normalized.endswith('/'):
                normalized = normalized[:-1]

            return normalized

        except Exception as e:
            logger.debug(f"URL normalization failed for {url}: {e}")
            return ""

    def _passes_filters(self, url: str, link_elem) -> bool:
        """
        Check if URL passes include/exclude filters.

        Args:
            url: Normalized URL
            link_elem: BeautifulSoup link element

        Returns:
            True if link should be considered
        """
        url_lower = url.lower()
        link_text = link_elem.get_text(strip=True).lower()

        # Exclude patterns (if specified)
        exclude_patterns = self.config.get('exclude_if_url_contains', [])
        if any(pattern.lower() in url_lower for pattern in exclude_patterns):
            logger.debug(f"Excluded by pattern: {url}")
            return False

        # Domain restriction (if specified)
        if self.config.get('require_same_domain', False):
            parsed = urlparse(url)
            if parsed.netloc != self.seed_domain:
                logger.debug(f"Excluded (different domain): {url}")
                return False

        # Include URL patterns (if specified, must match at least one)
        include_url_patterns = self.config.get('include_if_url_contains', [])
        if include_url_patterns:
            if not any(pattern.lower() in url_lower for pattern in include_url_patterns):
                return False

        # Include anchor patterns (if specified, must match at least one)
        include_anchor_patterns = self.config.get('include_if_anchor_contains', [])
        if include_anchor_patterns:
            if not any(pattern.lower() in link_text for pattern in include_anchor_patterns):
                return False

        return True

    def _get_context(self, link_elem) -> str:
        """
        Extract surrounding text context for a link.

        Args:
            link_elem: BeautifulSoup link element

        Returns:
            Context text (up to 200 chars)
        """
        # Get parent paragraph or containing element
        parent = link_elem.find_parent(['p', 'div', 'li', 'td', 'article'])

        if parent:
            context = parent.get_text(strip=True)
            # Limit length
            if len(context) > 200:
                context = context[:200] + "..."
            return context

        return ""

    def merge_with_existing(
        self,
        discovered: List[TrackedLink],
        existing: List[TrackedLink]
    ) -> List[TrackedLink]:
        """
        Merge discovered links with existing tracked links.

        Strategy:
        - Keep all existing links
        - Add new discovered links
        - Re-score all links
        - Return top N

        Args:
            discovered: Newly discovered links
            existing: Currently tracked links

        Returns:
            Merged list (top N by score)
        """
        # Create dict keyed by URL
        all_links = {}

        # Add existing (preserve first_seen)
        for link in existing:
            all_links[str(link.url)] = link

        # Add/update discovered
        for link in discovered:
            url_str = str(link.url)
            if url_str in all_links:
                # Update score but keep original first_seen
                all_links[url_str].score = link.score
            else:
                all_links[url_str] = link

        # Convert back to list and sort by score
        merged = list(all_links.values())
        merged.sort(key=lambda x: x.score, reverse=True)

        # Return top N
        max_urls = self.config.get('max_discovered_urls', 10)
        return merged[:max_urls]
