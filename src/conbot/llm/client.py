"""
OpenAI LLM client with caching and cost control.

Provides:
- Structured analysis of conference content changes
- In-memory caching to avoid duplicate API calls
- Cost tracking and limits
- Only called when content changes (not on every scan)
"""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from .prompts import (
    SYSTEM_PROMPT,
    format_change_summary_prompt,
    format_no_dates_prompt,
)
from ..models.conference import Deadline

logger = logging.getLogger(__name__)


class LLMCostError(Exception):
    """Raised when LLM cost limit exceeded."""
    pass


class LLMClient:
    """
    OpenAI client wrapper with caching and cost control.

    Features:
    - Only called when content changes (not every scan)
    - Response caching (24 hour TTL)
    - Cost tracking
    - Structured JSON output
    - Graceful fallback if API unavailable

    Example:
        >>> client = LLMClient(api_key="sk-...", model="gpt-4o-mini")
        >>> summary, metadata = client.analyze_change(
        ...     conference_id="uitp_summit",
        ...     conference_name="UITP Summit",
        ...     snippets=["Call for papers now open"],
        ...     deadlines=[]
        ... )
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        cache_ttl_hours: int = 24,
        max_monthly_cost: float = 10.0
    ):
        """
        Initialize LLM client.

        Args:
            api_key: OpenAI API key
            model: Model to use (default: gpt-4o-mini for cost efficiency)
            cache_ttl_hours: Cache TTL in hours (default: 24)
            max_monthly_cost: Maximum monthly spend in USD (default: $10)
        """
        self.api_key = api_key
        self.model = model
        self.cache_ttl_hours = cache_ttl_hours
        self.max_monthly_cost = max_monthly_cost

        # In-memory cache: {cache_key: (result, timestamp)}
        self._cache: Dict[str, Tuple[dict, datetime]] = {}

        # Cost tracking
        self._monthly_cost = 0.0
        self._call_count = 0

        # OpenAI client (lazy init)
        self._client = None

    @property
    def client(self):
        """Lazy-load OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
                logger.info(f"Initialized OpenAI client with model: {self.model}")
            except ImportError:
                raise ImportError(
                    "OpenAI library not installed. "
                    "Install with: pip install openai"
                )
        return self._client

    def analyze_change(
        self,
        conference_id: str,
        conference_name: str,
        snippets: List[str],
        deadlines: List[Deadline],
        keywords: Optional[List[str]] = None
    ) -> Tuple[str, Dict]:
        """
        Analyze changed conference content and generate summary.

        Args:
            conference_id: Conference identifier
            conference_name: Human-readable conference name
            snippets: Changed content snippets
            deadlines: Already extracted deadlines
            keywords: Matched keywords (optional)

        Returns:
            Tuple of (summary_text, metadata_dict)
            metadata includes: relevance_score, categories, key_changes

        Example:
            >>> summary, meta = client.analyze_change(
            ...     "uitp_summit",
            ...     "UITP Global Public Transport Summit",
            ...     ["Call for papers now open", "Deadline March 15"],
            ...     deadlines
            ... )
            >>> print(f"Summary: {summary}")
            >>> print(f"Relevance: {meta['relevance_score']}")
        """
        # Check cache first
        cache_key = self._make_cache_key(conference_id, snippets)
        cached = self._get_from_cache(cache_key)
        if cached:
            logger.info(f"Using cached LLM response for {conference_id}")
            return cached

        # Check cost limit
        if not self._can_make_call():
            logger.warning(f"Monthly cost limit reached: ${self._monthly_cost:.2f}")
            return self._fallback_summary(snippets, deadlines), {}

        # Prepare prompt
        deadlines_data = [
            {
                'date': dl.date.isoformat(),
                'type': dl.type.value,
                'source_text': dl.source_text
            }
            for dl in deadlines
        ]

        prompt = format_change_summary_prompt(
            conference_name=conference_name,
            changed_snippets=snippets[:20],  # Limit for token control
            relevant_keywords=keywords or [],
            extracted_deadlines=deadlines_data
        )

        # Call OpenAI API
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower for consistency
                max_tokens=500,
                response_format={"type": "json_object"}  # Force JSON output
            )

            result_text = response.choices[0].message.content
            self._track_cost(response.usage.total_tokens)

            # Parse JSON response
            try:
                result = json.loads(result_text)
                summary = result.get('summary', result_text)
                metadata = {
                    'relevance_score': result.get('relevance_score', 0.5),
                    'categories': result.get('categories', []),
                    'key_changes': result.get('key_changes', []),
                    'potential_dates': result.get('potential_dates', [])
                }
            except json.JSONDecodeError:
                logger.warning("LLM response not valid JSON, using raw text")
                summary = result_text
                metadata = {}

            # Cache result
            self._put_in_cache(cache_key, (summary, metadata))

            logger.info(
                f"LLM analysis complete for {conference_id}: "
                f"{len(summary)} chars, relevance={metadata.get('relevance_score', 'N/A')}"
            )

            return summary, metadata

        except Exception as e:
            logger.error(f"LLM API call failed: {e}", exc_info=True)
            return self._fallback_summary(snippets, deadlines), {}

    def _make_cache_key(self, conference_id: str, snippets: List[str]) -> str:
        """Generate cache key from conference ID and content."""
        content = conference_id + "|".join(snippets[:10])
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"{conference_id}:{content_hash}"

    def _get_from_cache(self, key: str) -> Optional[Tuple[str, Dict]]:
        """Retrieve from cache if not expired."""
        if key not in self._cache:
            return None

        result, timestamp = self._cache[key]
        age = datetime.now() - timestamp

        if age > timedelta(hours=self.cache_ttl_hours):
            # Expired
            del self._cache[key]
            return None

        return result

    def _put_in_cache(self, key: str, value: Tuple[str, Dict]):
        """Store in cache with timestamp."""
        self._cache[key] = (value, datetime.now())

    def _can_make_call(self) -> bool:
        """Check if we're within cost limits."""
        return self._monthly_cost < self.max_monthly_cost

    def _track_cost(self, tokens: int):
        """Track API call cost."""
        # gpt-4o-mini pricing (as of 2024): ~$0.15 per 1M input tokens, $0.60 per 1M output
        # Approximate as $0.40 per 1M tokens average
        cost_per_token = 0.40 / 1_000_000
        call_cost = tokens * cost_per_token

        self._monthly_cost += call_cost
        self._call_count += 1

        logger.debug(
            f"LLM call #{self._call_count}: {tokens} tokens, "
            f"${call_cost:.4f}, total: ${self._monthly_cost:.4f}"
        )

    def _fallback_summary(self, snippets: List[str], deadlines: List[Deadline]) -> str:
        """Generate simple summary without LLM."""
        parts = []

        if deadlines:
            parts.append(f"Found {len(deadlines)} deadline(s)")
            for dl in deadlines[:3]:
                parts.append(f"- {dl.type.value}: {dl.date}")

        if snippets:
            parts.append(f"Content changes detected in {len(snippets)} locations")

        return ". ".join(parts) if parts else "Content updated"

    def clear_cache(self):
        """Clear the response cache."""
        self._cache.clear()
        logger.info("LLM cache cleared")

    def get_stats(self) -> Dict:
        """Get usage statistics."""
        return {
            'call_count': self._call_count,
            'monthly_cost': round(self._monthly_cost, 4),
            'cache_size': len(self._cache),
            'cost_limit': self.max_monthly_cost,
            'remaining_budget': round(self.max_monthly_cost - self._monthly_cost, 4)
        }
