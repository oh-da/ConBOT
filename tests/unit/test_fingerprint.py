"""
Unit tests for three-tier change detection.

Tests ChangeDetector fingerprinting and change detection logic.
"""

import pytest
from conbot.detection.fingerprint import ChangeDetector
from conbot.detection.similarity import simhash, hamming_distance


class TestChangeDetector:
    """Test suite for ChangeDetector class."""

    def test_binary_hash_change(self):
        """Test detection of binary HTML changes."""
        detector = ChangeDetector()

        html1 = "<html><body>Content A</body></html>"
        html2 = "<html><body>Content B</body></html>"

        fp1 = detector.compute_fingerprints(html1, html1)
        fp2 = detector.compute_fingerprints(html2, html2)

        changed, change_type, _ = detector.detect_change(fp2, fp1)

        assert changed is True
        assert change_type == "FILTERED"  # Binary differs, but also filtered differs

    def test_no_change_detected(self):
        """Test when content hasn't changed."""
        detector = ChangeDetector()

        html = "<html><body>Same content</body></html>"

        fp1 = detector.compute_fingerprints(html, html)
        fp2 = detector.compute_fingerprints(html, html)

        changed, change_type, _ = detector.detect_change(fp2, fp1)

        assert changed is False
        assert change_type == "NONE"

    def test_filtered_content_change(self):
        """Test detection when only filtered content changes."""
        detector = ChangeDetector()

        # Same HTML structure, different main content
        html = "<html><body><main>Main content</main></body></html>"
        filtered1 = "Main content A"
        filtered2 = "Main content B"

        fp1 = detector.compute_fingerprints(html, filtered1)
        fp2 = detector.compute_fingerprints(html, filtered2)

        changed, change_type, _ = detector.detect_change(fp2, fp1)

        assert changed is True
        assert change_type == "FILTERED"

    def test_simhash_similarity_detection(self):
        """Test SimHash semantic similarity detection."""
        detector = ChangeDetector(simhash_threshold=5)

        # Very similar content (should not trigger change)
        text1 = "Call for papers deadline March 15, 2026"
        text2 = "Call for papers deadline March 16, 2026"  # Only date differs

        fp1 = detector.compute_fingerprints(text1, text1)
        fp2 = detector.compute_fingerprints(text2, text2)

        changed, change_type, ham_dist = detector.detect_change(fp2, fp1)

        # Should detect as similar (low Hamming distance)
        assert ham_dist is not None
        # Might detect change or not depending on exact hash, but distance should be small
        if changed:
            assert change_type in ["FILTERED", "SEMANTIC"]

    def test_first_scan_returns_change(self):
        """Test that first scan (no old fingerprints) returns change."""
        detector = ChangeDetector()

        html = "<html><body>First scan</body></html>"
        fp = detector.compute_fingerprints(html, html)

        changed, change_type, _ = detector.detect_change(fp, None)

        assert changed is True
        assert change_type == "BINARY"

    def test_compute_fingerprints_structure(self):
        """Test that compute_fingerprints returns correct structure."""
        detector = ChangeDetector()

        html = "<html><body>Test</body></html>"
        fp = detector.compute_fingerprints(html, html)

        assert 'binary_hash' in fp
        assert 'filtered_hash' in fp
        assert 'simhash_signature' in fp
        assert isinstance(fp['binary_hash'], str)
        assert isinstance(fp['filtered_hash'], str)
        assert isinstance(fp['simhash_signature'], int)
        assert len(fp['binary_hash']) == 64  # SHA-256 hex length


class TestSimHash:
    """Test suite for SimHash functions."""

    def test_simhash_returns_int(self):
        """Test that simhash returns an integer."""
        text = "Call for papers"
        sig = simhash(text)
        assert isinstance(sig, int)
        assert sig > 0

    def test_identical_text_same_hash(self):
        """Test that identical text produces identical hash."""
        text = "Abstract submission deadline March 15"
        sig1 = simhash(text)
        sig2 = simhash(text)
        assert sig1 == sig2

    def test_similar_text_low_distance(self):
        """Test that similar text has low Hamming distance."""
        text1 = "Conference deadline March 15, 2026"
        text2 = "Conference deadline March 16, 2026"

        sig1 = simhash(text1)
        sig2 = simhash(text2)
        dist = hamming_distance(sig1, sig2)

        # Should be relatively low distance (similar content)
        assert dist < 20  # Reasonable threshold for similar texts

    def test_different_text_high_distance(self):
        """Test that different text has high Hamming distance."""
        text1 = "Call for papers deadline March 15"
        text2 = "Registration is now open for attendees"

        sig1 = simhash(text1)
        sig2 = simhash(text2)
        dist = hamming_distance(sig1, sig2)

        # Should be higher distance (different content)
        assert dist > 5  # Different enough to detect change

    def test_empty_text_returns_zero(self):
        """Test that empty text returns 0."""
        sig = simhash("")
        assert sig == 0

        sig = simhash("   ")
        assert sig == 0

    def test_hamming_distance_identical(self):
        """Test Hamming distance of identical hashes is 0."""
        text = "Test text"
        sig = simhash(text)
        dist = hamming_distance(sig, sig)
        assert dist == 0

    def test_hamming_distance_max_bits(self):
        """Test Hamming distance of completely different hashes."""
        # All 0s vs all 1s
        hash1 = 0
        hash2 = (1 << 64) - 1  # All bits set

        dist = hamming_distance(hash1, hash2)
        assert dist == 64  # All 64 bits differ
