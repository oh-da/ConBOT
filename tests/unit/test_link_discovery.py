"""
Unit tests for link discovery and URL scoring.

Tests LinkScorer and LinkDiscovery functionality.
"""

import pytest
from conbot.discovery.scoring import LinkScorer
from conbot.discovery.link_finder import LinkDiscovery


class TestLinkScorer:
    """Test suite for LinkScorer."""

    def test_cfp_url_pattern_high_score(self):
        """Test that CFP URL patterns get high scores."""
        scorer = LinkScorer()
        score = scorer.score_link(
            url="https://example.com/call-for-papers",
            link_text="Submit your abstract",
            title=""
        )

        assert score > 3.0  # Should get URL pattern bonus + keyword bonus

    def test_generic_url_low_score(self):
        """Test that generic URLs get low scores."""
        scorer = LinkScorer()
        score = scorer.score_link(
            url="https://example.com/about",
            link_text="About us",
            title=""
        )

        assert score == 0.0  # No relevant patterns or keywords

    def test_custom_keywords_boost(self):
        """Test that custom keywords boost score."""
        scorer = LinkScorer(custom_keywords=["trb", "annual meeting"])
        score = scorer.score_link(
            url="https://example.com/trb-annual-meeting",
            link_text="TRB Annual Meeting Information",
            title=""
        )

        # Should get: URL pattern + custom keywords + high-value keywords
        assert score > 5.0

    def test_long_url_penalty(self):
        """Test penalty for very long URLs."""
        scorer = LinkScorer()

        short_url = "https://example.com/cfp"
        long_url = "https://example.com/cfp?" + "param=value&" * 20

        score_short = scorer.score_link(short_url, "CFP", "")
        score_long = scorer.score_link(long_url, "CFP", "")

        assert score_long < score_short  # Long URL should be penalized

    def test_year_match_bonus(self):
        """Test bonus for current year in URL."""
        scorer = LinkScorer()

        score = scorer.score_link(
            url="https://example.com/conference/2026/cfp",
            link_text="Call for papers",
            title=""
        )

        # Should get year bonus
        assert score > 4.0

    def test_rank_links(self):
        """Test ranking multiple links."""
        scorer = LinkScorer()

        links = [
            {'url': 'https://ex.com/about', 'text': 'About', 'title': ''},
            {'url': 'https://ex.com/cfp', 'text': 'Call for Papers', 'title': ''},
            {'url': 'https://ex.com/register', 'text': 'Register', 'title': ''},
            {'url': 'https://ex.com/deadline', 'text': 'Important Dates', 'title': ''},
        ]

        ranked = scorer.rank_links(links)

        # CFP and deadline should be ranked higher
        assert ranked[0]['url'] in ['https://ex.com/cfp', 'https://ex.com/deadline']
        assert ranked[-1]['url'] == 'https://ex.com/about'  # About should be last


class TestLinkDiscovery:
    """Test suite for LinkDiscovery."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config = {
            'include_if_url_contains': ['call', 'paper', 'deadline'],
            'include_if_anchor_contains': ['submit', 'cfp'],
            'exclude_if_url_contains': ['donate', 'privacy'],
            'max_discovered_urls': 5,
        }

    def test_discover_links_from_html(self):
        """Test link discovery from HTML."""
        html = """
        <html><body>
            <a href="/call-for-papers">Submit Papers</a>
            <a href="/about">About Us</a>
            <a href="/donate">Donate</a>
            <a href="/important-dates">Deadlines</a>
        </body></html>
        """

        discovery = LinkDiscovery(
            seed_url="https://example.com",
            config=self.config
        )

        tracked = discovery.discover_links(html)

        # Should find CFP and deadline links, exclude donate
        assert len(tracked) >= 1
        urls = [str(link.url) for link in tracked]
        assert any('call-for-papers' in url for url in urls)
        assert not any('donate' in url for url in urls)

    def test_url_normalization(self):
        """Test URL normalization removes query params and fragments."""
        discovery = LinkDiscovery(
            seed_url="https://example.com",
            config=self.config
        )

        normalized = discovery._normalize_url("https://example.com/page?id=123#section")
        assert normalized == "https://example.com/page"

    def test_same_domain_restriction(self):
        """Test same-domain filtering."""
        html = """
        <html><body>
            <a href="/call-for-papers">Internal CFP</a>
            <a href="https://external.com/cfp">External CFP</a>
        </body></html>
        """

        config = self.config.copy()
        config['require_same_domain'] = True

        discovery = LinkDiscovery(
            seed_url="https://example.com",
            config=config
        )

        tracked = discovery.discover_links(html)

        # Should only find internal link
        urls = [str(link.url) for link in tracked]
        assert all('example.com' in url for url in urls)

    def test_max_discovered_urls_limit(self):
        """Test that max_discovered_urls is respected."""
        html = "<html><body>" + "\n".join(
            f'<a href="/page{i}">CFP {i}</a>' for i in range(20)
        ) + "</body></html>"

        discovery = LinkDiscovery(
            seed_url="https://example.com",
            config=self.config  # max_discovered_urls=5
        )

        tracked = discovery.discover_links(html)

        assert len(tracked) <= 5  # Should be limited to max
