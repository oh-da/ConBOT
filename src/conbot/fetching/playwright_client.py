"""
Playwright client for rendering JavaScript-heavy pages.

Provides a wrapper around Playwright's sync API for fetching pages
that require JavaScript execution to render content.
"""

from typing import Optional
import logging

logger = logging.getLogger(__name__)


class PlaywrightClient:
    """
    Wrapper for Playwright browser automation.

    Launches a headless Chromium browser and renders pages with full
    JavaScript execution. Suitable for modern SPAs and JS-heavy sites.

    Example:
        >>> client = PlaywrightClient(timeout_ms=30000)
        >>> html = client.fetch("https://example.com")
        >>> client.close()

        # Or use as context manager:
        >>> with PlaywrightClient() as client:
        ...     html = client.fetch("https://example.com")
    """

    def __init__(self, timeout_ms: int = 25000, headless: bool = True):
        """
        Initialize Playwright client.

        Args:
            timeout_ms: Page load timeout in milliseconds
            headless: Run browser in headless mode (default: True)

        Note:
            Browser is not launched until first fetch() call (lazy initialization)
        """
        self.timeout_ms = timeout_ms
        self.headless = headless
        self._playwright = None
        self._browser = None

    def _ensure_browser(self):
        """Lazy initialization of Playwright browser."""
        if self._browser is not None:
            return

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ImportError(
                "Playwright not installed. Install with: pip install playwright && "
                "playwright install chromium"
            )

        logger.debug("Launching Playwright browser")
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            # Performance optimizations
            args=[
                '--disable-blink-features=AutomationControlled',  # Avoid detection
                '--disable-dev-shm-usage',  # Overcome limited resource problems
                '--no-sandbox',  # Required for some environments
            ]
        )
        logger.info("Playwright browser launched successfully")

    def fetch(self, url: str, wait_for_selector: Optional[str] = None) -> str:
        """
        Fetch page content with JavaScript rendering.

        Args:
            url: URL to fetch
            wait_for_selector: Optional CSS selector to wait for before extracting content

        Returns:
            Rendered HTML content as string

        Raises:
            Exception: If page load fails or times out

        Example:
            >>> html = client.fetch("https://example.com", wait_for_selector="#content")
        """
        self._ensure_browser()

        page = self._browser.new_page()
        try:
            logger.debug(f"Navigating to {url}")

            # Navigate and wait for network to be idle
            page.goto(
                url,
                timeout=self.timeout_ms,
                wait_until="networkidle"  # Wait for no more than 2 network connections for 500ms
            )

            # Wait for specific selector if provided
            if wait_for_selector:
                logger.debug(f"Waiting for selector: {wait_for_selector}")
                page.wait_for_selector(wait_for_selector, timeout=self.timeout_ms)

            # Additional wait for dynamic content to load
            # Many SPAs have delayed rendering after network idle
            page.wait_for_timeout(2000)  # 2 second grace period

            # Get fully rendered HTML
            html = page.content()

            logger.info(
                f"Successfully rendered {url} with Playwright "
                f"({len(html)} bytes, {len(page.frames)} frames)"
            )

            return html

        except Exception as e:
            logger.error(f"Playwright error for {url}: {e}")
            raise

        finally:
            page.close()

    def close(self):
        """Clean up browser resources."""
        if self._browser:
            logger.debug("Closing Playwright browser")
            self._browser.close()
            self._browser = None

        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def __enter__(self):
        """Context manager entry."""
        self._ensure_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit (cleanup)."""
        self.close()

    def __del__(self):
        """Destructor to ensure browser is closed."""
        self.close()
