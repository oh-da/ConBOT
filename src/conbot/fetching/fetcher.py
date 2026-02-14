"""
Web content fetcher with automatic fallback and retry logic.

Implements a two-tier fetching strategy:
1. Try requests (fast, lightweight)
2. Fall back to Playwright if JS rendering needed

Includes exponential backoff retry logic and polite throttling.
"""

import time
from typing import Optional, Tuple
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import requests
import logging

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when fetching fails after all retries."""
    pass


class Fetcher:
    """
    Fetches web pages with automatic fallback from requests → playwright.

    Features:
    - Exponential backoff retry (3 attempts by default)
    - Polite throttling (1.5s between requests by default)
    - Automatic JS detection and Playwright fallback
    - Realistic User-Agent headers

    Example:
        >>> fetcher = Fetcher(throttle_seconds=2.0, max_retries=3)
        >>> html, method = fetcher.fetch("https://example.com")
        >>> print(f"Fetched with {method}: {len(html)} bytes")
    """

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        throttle_seconds: float = 1.5,
        timeout_seconds: int = 25,
        max_retries: int = 3,
        backoff_factor: float = 1.0
    ):
        """
        Initialize fetcher.

        Args:
            throttle_seconds: Minimum time between requests to same domain
            timeout_seconds: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            backoff_factor: Multiplier for exponential backoff (wait = backoff * 2^retry)
        """
        self.throttle_seconds = throttle_seconds
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._last_request_time = 0
        self._playwright_client: Optional['PlaywrightClient'] = None

    def _get_session(self) -> requests.Session:
        """Create requests session with retry logic."""
        session = requests.Session()

        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
            raise_on_status=False  # We'll handle status ourselves
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _throttle(self):
        """Ensure minimum time between requests (polite crawling)."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.throttle_seconds:
            sleep_time = self.throttle_seconds - elapsed
            logger.debug(f"Throttling: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.time()

    def fetch(self, url: str, force_playwright: bool = False) -> Tuple[str, str]:
        """
        Fetch URL content with automatic fallback.

        Args:
            url: URL to fetch
            force_playwright: If True, skip requests and use Playwright directly

        Returns:
            Tuple of (html_content, method_used)
            method_used is either "requests" or "playwright"

        Raises:
            FetchError: If fetch fails after all retries

        Example:
            >>> html, method = fetcher.fetch("https://example.com")
            >>> if method == "playwright":
            ...     print("Page required JS rendering")
        """
        self._throttle()

        if force_playwright:
            logger.info(f"Force Playwright mode for {url}")
            return self._fetch_with_playwright(url), "playwright"

        try:
            html = self._fetch_with_requests(url)

            # Heuristic: Check if page needs JS rendering
            if self._needs_js_rendering(html):
                logger.info(f"JS markers detected in {url}, switching to Playwright")
                return self._fetch_with_playwright(url), "playwright"

            return html, "requests"

        except requests.exceptions.RequestException as e:
            logger.warning(f"Requests failed for {url}: {e}, trying Playwright")
            # Fallback to Playwright on any error
            try:
                return self._fetch_with_playwright(url), "playwright"
            except Exception as pw_error:
                raise FetchError(
                    f"Both requests and Playwright failed for {url}. "
                    f"Requests error: {e}, Playwright error: {pw_error}"
                ) from pw_error

    def _fetch_with_requests(self, url: str) -> str:
        """
        Fetch using requests library.

        Args:
            url: URL to fetch

        Returns:
            HTML content as string

        Raises:
            requests.exceptions.RequestException: If fetch fails
        """
        session = self._get_session()
        headers = {
            'User-Agent': self.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        logger.debug(f"Fetching {url} with requests")
        response = session.get(url, headers=headers, timeout=self.timeout_seconds)

        # Check for error status codes
        if response.status_code == 404:
            logger.warning(f"404 Not Found: {url}")
            return ""  # Return empty string for 404s, don't raise

        response.raise_for_status()
        logger.info(f"Successfully fetched {url} ({len(response.text)} bytes)")
        return response.text

    def _fetch_with_playwright(self, url: str) -> str:
        """
        Fetch using Playwright for JS-heavy sites.

        Args:
            url: URL to fetch

        Returns:
            Rendered HTML content as string

        Raises:
            Exception: If Playwright fetch fails
        """
        # Lazy import and initialization
        if self._playwright_client is None:
            from .playwright_client import PlaywrightClient
            self._playwright_client = PlaywrightClient(
                timeout_ms=self.timeout_seconds * 1000
            )

        logger.debug(f"Fetching {url} with Playwright")
        html = self._playwright_client.fetch(url)
        logger.info(f"Successfully fetched {url} with Playwright ({len(html)} bytes)")
        return html

    def _needs_js_rendering(self, html: str) -> bool:
        """
        Heuristic to detect if page needs JavaScript rendering.

        Checks for:
        - Common JS framework markers (React, Vue, Angular, Next.js)
        - Very small page size (likely empty shell)

        Args:
            html: Raw HTML content

        Returns:
            True if page likely needs JS rendering
        """
        # Check for common JS framework markers
        js_markers = [
            '<div id="root"',           # React
            '<div id="app"',            # Vue
            'data-react-root',          # React
            'ng-app',                   # Angular
            '__NEXT_DATA__',            # Next.js
            'nuxt',                     # Nuxt
            'data-reactroot',           # React (older)
            '<div id="__next"',         # Next.js
        ]

        html_lower = html.lower()

        for marker in js_markers:
            if marker.lower() in html_lower:
                logger.debug(f"Found JS marker: {marker}")
                return True

        # Check if page is suspiciously small (likely empty shell)
        if len(html) < 5000:
            logger.debug(f"Page is very small ({len(html)} bytes), likely needs JS")
            return True

        return False

    def close(self):
        """Clean up resources (close Playwright browser if initialized)."""
        if self._playwright_client:
            logger.debug("Closing Playwright client")
            self._playwright_client.close()
            self._playwright_client = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit (cleanup)."""
        self.close()
