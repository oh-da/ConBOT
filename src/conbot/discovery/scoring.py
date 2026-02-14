"""
URL relevance scoring for link discovery.

Scores candidate URLs based on:
- URL patterns (/cfp, /call-for-papers, /deadline)
- Anchor text keywords (call for, submit, deadline)
- Custom conference-specific keywords
"""

import re
from typing import List
import logging

logger = logging.getLogger(__name__)


class LinkScorer:
    """
    Score candidate URLs for relevance to CFP/deadlines.

    Scoring algorithm:
    1. URL pattern matching (+2-3 points)
    2. Anchor text keyword matching (+1-2 points)
    3. Custom keywords (+1.5 points)
    4. Penalties for very long URLs (-50%)

    Example:
        >>> scorer = LinkScorer(custom_keywords=["annual meeting", "trb"])
        >>> score = scorer.score_link(
        ...     url="https://example.com/annual-meeting/call-for-papers",
        ...     link_text="Submit your abstract",
        ...     title="CFP Information"
        ... )
        >>> print(f"Relevance score: {score}")
    """

    # High-value URL patterns (regex → score)
    URL_PATTERNS = {
        r'/cfp|call-for-papers|call_for_papers': 3.0,
        r'/submit|submission': 2.5,
        r'/deadline|important-dates|key-dates': 2.5,
        r'/program|programme|papers': 2.0,
        r'/abstract': 2.0,
        r'/\d{4}/': 1.5,  # Year in URL (e.g., /2026/)
        r'/annual-meeting|annual_meeting': 2.0,
    }

    # High-value keywords in anchor text
    HIGH_VALUE_KEYWORDS = [
        'call for papers',
        'call for abstracts',
        'call for proposals',
        'cfp',
        'submit',
        'submission',
        'deadline',
        'important dates',
        'key dates',
    ]

    # Medium-value keywords
    MEDIUM_VALUE_KEYWORDS = [
        'participate',
        'contribute',
        'authors',
        'speakers',
        'presenters',
        'abstract',
        'paper',
        'proposal',
    ]

    def __init__(self, custom_keywords: List[str] = None):
        """
        Initialize link scorer.

        Args:
            custom_keywords: Conference-specific keywords for scoring boost
        """
        self.custom_keywords = custom_keywords or []

    def score_link(
        self,
        url: str,
        link_text: str,
        title: str = "",
        context: str = ""
    ) -> float:
        """
        Score a link for CFP/deadline relevance.

        Args:
            url: The URL to score
            link_text: Anchor text of the link
            title: Title attribute (if any)
            context: Surrounding text context

        Returns:
            Relevance score (0.0-10.0+, higher is more relevant)

        Example:
            >>> score = scorer.score_link(
            ...     "https://conf.org/2026/cfp",
            ...     "Call for Papers",
            ...     "CFP Page"
            ... )
            >>> if score > 5.0:
            ...     print("Highly relevant link")
        """
        score = 0.0
        combined_text = f"{link_text} {title} {context}".lower()
        url_lower = url.lower()

        # 1. URL pattern matching
        for pattern, pattern_score in self.URL_PATTERNS.items():
            if re.search(pattern, url_lower):
                score += pattern_score
                logger.debug(f"URL pattern match: {pattern} (+{pattern_score})")

        # 2. High-value keyword matching
        for keyword in self.HIGH_VALUE_KEYWORDS:
            if keyword in combined_text:
                score += 2.0
                logger.debug(f"High-value keyword: '{keyword}' (+2.0)")

        # 3. Medium-value keyword matching
        for keyword in self.MEDIUM_VALUE_KEYWORDS:
            if keyword in combined_text:
                score += 1.0
                logger.debug(f"Medium-value keyword: '{keyword}' (+1.0)")

        # 4. Custom keywords
        for keyword in self.custom_keywords:
            if keyword.lower() in combined_text:
                score += 1.5
                logger.debug(f"Custom keyword: '{keyword}' (+1.5)")

        # 5. Penalties

        # Penalty for very long URLs (often pagination/filters)
        if len(url) > 150:
            score *= 0.5
            logger.debug(f"Long URL penalty: {len(url)} chars (-50%)")

        # Penalty if URL looks like a file download
        if re.search(r'\.(pdf|doc|docx|ppt|pptx|zip)$', url_lower):
            score *= 0.7
            logger.debug("File download penalty (-30%)")

        # 6. Bonuses

        # Bonus for concise, relevant link text
        if 5 < len(link_text) < 50 and any(kw in link_text.lower() for kw in ['call', 'submit', 'deadline']):
            score += 0.5
            logger.debug("Concise relevant text bonus (+0.5)")

        # Bonus for year match (conference is likely current)
        current_year = 2026  # Could be dynamic
        if str(current_year) in url or str(current_year) in combined_text:
            score += 1.0
            logger.debug(f"Current year match (+1.0)")

        return round(score, 2)

    def filter_by_score(
        self,
        scored_links: List[tuple],
        threshold: float = 2.0
    ) -> List[tuple]:
        """
        Filter links by minimum score threshold.

        Args:
            scored_links: List of (url, score, ...) tuples
            threshold: Minimum score to keep

        Returns:
            Filtered list of links

        Example:
            >>> scored = [(url1, 5.0), (url2, 1.0), (url3, 3.5)]
            >>> relevant = scorer.filter_by_score(scored, threshold=2.0)
            >>> # Returns only url1 and url3
        """
        return [link for link in scored_links if link[1] >= threshold]

    def rank_links(
        self,
        links: List[Dict[str, any]]
    ) -> List[Dict[str, any]]:
        """
        Score and rank a list of link dictionaries.

        Args:
            links: List of dicts with 'url', 'text', 'title', 'context' keys

        Returns:
            Sorted list (highest score first) with 'score' added

        Example:
            >>> links = [
            ...     {'url': 'https://...', 'text': 'Call for papers', 'title': ''},
            ...     {'url': 'https://...', 'text': 'About', 'title': ''},
            ... ]
            >>> ranked = scorer.rank_links(links)
            >>> for link in ranked[:5]:
            ...     print(f"{link['score']}: {link['text']}")
        """
        for link in links:
            link['score'] = self.score_link(
                url=link.get('url', ''),
                link_text=link.get('text', ''),
                title=link.get('title', ''),
                context=link.get('context', '')
            )

        # Sort by score descending
        ranked = sorted(links, key=lambda x: x['score'], reverse=True)

        logger.info(f"Ranked {len(ranked)} links, top score: {ranked[0]['score'] if ranked else 0}")
        return ranked
