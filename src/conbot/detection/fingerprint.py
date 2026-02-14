"""
Three-tier change detection using fingerprinting.

Implements a cascading approach to detect content changes:
1. Binary hash (SHA-256 of raw HTML) - fastest, exact match
2. Filtered hash (SHA-256 of content without nav/footer) - ignores noise
3. SimHash (semantic similarity) - detects meaningful changes

This approach minimizes false positives while catching real content updates.
"""

import hashlib
from typing import Dict, Optional, Tuple
from .similarity import simhash, hamming_distance
import logging

logger = logging.getLogger(__name__)


class ChangeDetector:
    """
    Three-tier change detection system.

    Tiers (checked in order):
    1. **Binary**: SHA-256 hash of raw HTML
       - Fastest check
       - Detects any change (including timestamps, ads)
       - High false positive rate

    2. **Filtered**: SHA-256 hash of filtered content
       - Removes navigation, footer, ads
       - Lower false positive rate
       - Still sensitive to minor changes

    3. **Semantic**: SimHash with Hamming distance
       - Detects semantically meaningful changes
       - Threshold-based (default: ≤5 = similar)
       - Lowest false positive rate

    Example:
        >>> detector = ChangeDetector(simhash_threshold=5)
        >>>
        >>> # First scan
        >>> fp1 = detector.compute_fingerprints(html1, filtered1)
        >>>
        >>> # Second scan
        >>> fp2 = detector.compute_fingerprints(html2, filtered2)
        >>> changed, change_type, distance = detector.detect_change(fp2, fp1)
        >>>
        >>> if changed:
        ...     print(f"Change detected: {change_type} (hamming: {distance})")
    """

    def __init__(self, simhash_threshold: int = 5):
        """
        Initialize change detector.

        Args:
            simhash_threshold: Maximum Hamming distance to consider similar (default: 5)
                Lower = stricter (fewer false positives, might miss small updates)
                Higher = looser (more false positives, catches all updates)
        """
        self.simhash_threshold = simhash_threshold

    @staticmethod
    def compute_fingerprints(raw_html: str, filtered_content: str) -> Dict[str, any]:
        """
        Compute all three fingerprints for content.

        Args:
            raw_html: Raw HTML from web page
            filtered_content: Filtered content (nav/footer removed)

        Returns:
            Dictionary with keys:
                - binary_hash: SHA-256 hex of raw HTML
                - filtered_hash: SHA-256 hex of filtered content
                - simhash_signature: SimHash integer signature

        Example:
            >>> fingerprints = ChangeDetector.compute_fingerprints(html, filtered)
            >>> print(fingerprints['binary_hash'][:16])  # First 16 chars
            a1b2c3d4e5f6g7h8
        """
        # Tier 1: Binary hash (raw HTML)
        binary_hash = hashlib.sha256(raw_html.encode('utf-8')).hexdigest()

        # Tier 2: Filtered hash (cleaned content)
        filtered_hash = hashlib.sha256(filtered_content.encode('utf-8')).hexdigest()

        # Tier 3: SimHash (semantic signature)
        simhash_signature = simhash(filtered_content)

        logger.debug(
            f"Computed fingerprints: binary={binary_hash[:8]}..., "
            f"filtered={filtered_hash[:8]}..., simhash={simhash_signature}"
        )

        return {
            'binary_hash': binary_hash,
            'filtered_hash': filtered_hash,
            'simhash_signature': simhash_signature,
        }

    def detect_change(
        self,
        new_fingerprints: Dict[str, any],
        old_fingerprints: Optional[Dict[str, any]]
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Detect changes using three-tier approach.

        Checks tiers in order (fast to slow):
        1. Binary hash comparison (instant)
        2. Filtered hash comparison (instant)
        3. SimHash Hamming distance (instant)

        Args:
            new_fingerprints: Fingerprints from current scan
            old_fingerprints: Fingerprints from previous scan (None for first scan)

        Returns:
            Tuple of (change_detected, change_type, hamming_distance)

            change_detected: True if change found
            change_type: "BINARY" | "FILTERED" | "SEMANTIC" | "NONE"
            hamming_distance: Hamming distance if SimHash checked, else None

        Example:
            >>> changed, type_, dist = detector.detect_change(new_fp, old_fp)
            >>> if changed and type_ == "SEMANTIC":
            ...     print(f"Meaningful change (Hamming: {dist})")
            >>> elif not changed:
            ...     print("No significant change")
        """
        # First scan - no previous fingerprints
        if old_fingerprints is None:
            logger.info("First scan - no previous fingerprints to compare")
            return True, "BINARY", None

        # Tier 1: Binary hash comparison (fastest)
        if new_fingerprints['binary_hash'] == old_fingerprints['binary_hash']:
            logger.debug("Tier 1: Binary hashes match - no change")
            return False, "NONE", None

        logger.debug("Tier 1: Binary hashes differ, checking tier 2")

        # Tier 2: Filtered hash comparison
        if new_fingerprints['filtered_hash'] != old_fingerprints['filtered_hash']:
            logger.info("Tier 2: Filtered content changed - FILTERED change detected")
            return True, "FILTERED", None

        logger.debug("Tier 2: Filtered hashes match, checking tier 3")

        # Tier 3: SimHash semantic similarity
        old_simhash = old_fingerprints.get('simhash_signature')
        new_simhash = new_fingerprints['simhash_signature']

        if old_simhash is None:
            # Old fingerprints don't have SimHash (legacy data)
            logger.warning("Old fingerprints missing SimHash, treating as binary change")
            return True, "BINARY", None

        # Compute Hamming distance
        ham_dist = hamming_distance(new_simhash, old_simhash)
        logger.debug(f"Tier 3: Hamming distance = {ham_dist} (threshold = {self.simhash_threshold})")

        if ham_dist > self.simhash_threshold:
            logger.info(
                f"Tier 3: Hamming distance {ham_dist} > {self.simhash_threshold} - "
                f"SEMANTIC change detected"
            )
            return True, "SEMANTIC", ham_dist

        logger.info(
            f"Tier 3: Hamming distance {ham_dist} <= {self.simhash_threshold} - "
            f"content similar, no significant change"
        )
        return False, "NONE", ham_dist

    def tune_threshold(
        self,
        fingerprints_pairs: list[Tuple[Dict, Dict]],
        labels: list[bool]
    ) -> int:
        """
        Tune SimHash threshold based on labeled examples.

        Useful for finding optimal threshold to minimize false positives/negatives
        for specific conference website patterns.

        Args:
            fingerprints_pairs: List of (new_fingerprints, old_fingerprints) tuples
            labels: List of True (real change) or False (no change) for each pair

        Returns:
            Optimal threshold value

        Example:
            >>> pairs = [(fp1_new, fp1_old), (fp2_new, fp2_old), ...]
            >>> labels = [True, False, True, ...]  # Ground truth
            >>> optimal_threshold = detector.tune_threshold(pairs, labels)
            >>> detector.simhash_threshold = optimal_threshold
        """
        # Try thresholds from 1 to 20
        best_threshold = self.simhash_threshold
        best_accuracy = 0

        for threshold in range(1, 21):
            self.simhash_threshold = threshold
            correct = 0

            for (new_fp, old_fp), expected_change in zip(fingerprints_pairs, labels):
                detected_change, _, _ = self.detect_change(new_fp, old_fp)
                if detected_change == expected_change:
                    correct += 1

            accuracy = correct / len(labels)

            if accuracy > best_accuracy:
                best_accuracy = accuracy
                best_threshold = threshold

        logger.info(
            f"Optimal threshold: {best_threshold} (accuracy: {best_accuracy:.2%})"
        )

        self.simhash_threshold = best_threshold
        return best_threshold
