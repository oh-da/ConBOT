"""
SimHash and similarity functions for semantic change detection.

Implements SimHash algorithm for detecting near-duplicate and similar content.
Uses Hamming distance to measure similarity between SimHash signatures.
"""

import re
from collections import defaultdict
from typing import List
import logging

logger = logging.getLogger(__name__)


def simhash(text: str, hash_bits: int = 64) -> int:
    """
    Compute SimHash signature for text.

    SimHash is a locality-sensitive hashing algorithm that produces similar
    hash values for similar documents. Used for detecting semantic changes
    rather than exact binary changes.

    Algorithm:
    1. Tokenize text into words
    2. For each word, compute hash and weight (frequency)
    3. Build weighted bit vector
    4. Convert vector to final hash (bits >= 0 → 1, else → 0)

    Args:
        text: Input text to hash
        hash_bits: Number of bits in hash (default: 64)

    Returns:
        SimHash signature as integer

    Example:
        >>> sig1 = simhash("Call for papers deadline March 15")
        >>> sig2 = simhash("Call for papers deadline March 16")
        >>> distance = hamming_distance(sig1, sig2)
        >>> print(f"Hamming distance: {distance}")  # Should be low (similar)
    """
    if not text or not text.strip():
        return 0

    # Tokenize into words (alphanumeric only)
    tokens = re.findall(r'\w+', text.lower())

    if not tokens:
        return 0

    # Count token frequencies
    token_freq = defaultdict(int)
    for token in tokens:
        token_freq[token] += 1

    # Initialize weighted bit vector
    vector = [0] * hash_bits

    # For each token, compute hash and update vector
    for token, freq in token_freq.items():
        # Use Python's built-in hash (fast, good distribution)
        token_hash = hash(token)

        # Update vector based on hash bits
        for i in range(hash_bits):
            bit = (token_hash >> i) & 1
            if bit:
                vector[i] += freq
            else:
                vector[i] -= freq

    # Generate final signature: 1 if vector[i] >= 0, else 0
    signature = 0
    for i in range(hash_bits):
        if vector[i] >= 0:
            signature |= (1 << i)

    logger.debug(f"SimHash computed: {signature} ({bin(signature).count('1')}/{hash_bits} bits set)")
    return signature


def hamming_distance(hash1: int, hash2: int) -> int:
    """
    Compute Hamming distance between two SimHash signatures.

    Hamming distance = number of differing bits.
    Low distance (≤5) indicates similar content.
    High distance (>5) indicates different content.

    Args:
        hash1: First SimHash signature
        hash2: Second SimHash signature

    Returns:
        Number of differing bits (0 to hash_bits)

    Example:
        >>> sig1 = simhash("text A")
        >>> sig2 = simhash("text B")
        >>> dist = hamming_distance(sig1, sig2)
        >>> if dist <= 5:
        ...     print("Similar content")
        ... else:
        ...     print("Different content")
    """
    # XOR gives 1 where bits differ
    xor = hash1 ^ hash2

    # Count number of 1s (Brian Kernighan's algorithm)
    distance = 0
    while xor:
        distance += 1
        xor &= xor - 1  # Clear rightmost set bit

    return distance


def are_similar(hash1: int, hash2: int, threshold: int = 5) -> bool:
    """
    Check if two SimHash signatures represent similar content.

    Args:
        hash1: First SimHash signature
        hash2: Second SimHash signature
        threshold: Maximum Hamming distance for similarity (default: 5)

    Returns:
        True if Hamming distance <= threshold (similar), False otherwise

    Example:
        >>> sig1 = simhash("Conference deadline March 15")
        >>> sig2 = simhash("Conference deadline March 16")
        >>> if are_similar(sig1, sig2):
        ...     print("Content is similar, not a significant change")
    """
    distance = hamming_distance(hash1, hash2)
    return distance <= threshold


def batch_simhash(texts: List[str], hash_bits: int = 64) -> List[int]:
    """
    Compute SimHash for multiple texts efficiently.

    Args:
        texts: List of texts to hash
        hash_bits: Number of bits in hash

    Returns:
        List of SimHash signatures (same order as input)

    Example:
        >>> texts = ["text 1", "text 2", "text 3"]
        >>> signatures = batch_simhash(texts)
        >>> for text, sig in zip(texts, signatures):
        ...     print(f"{text}: {sig}")
    """
    return [simhash(text, hash_bits) for text in texts]


def find_duplicates(texts: List[str], threshold: int = 5) -> List[List[int]]:
    """
    Find groups of similar texts using SimHash.

    Args:
        texts: List of texts to compare
        threshold: Maximum Hamming distance for similarity

    Returns:
        List of groups, where each group is a list of indices of similar texts

    Example:
        >>> texts = ["Call for papers", "CFP", "Submit papers", "Registration"]
        >>> groups = find_duplicates(texts, threshold=10)
        >>> for group in groups:
        ...     print(f"Similar texts: {[texts[i] for i in group]}")
    """
    signatures = batch_simhash(texts)
    n = len(signatures)

    # Track which texts have been grouped
    grouped = [False] * n
    groups = []

    for i in range(n):
        if grouped[i]:
            continue

        # Start new group
        group = [i]
        grouped[i] = True

        # Find similar texts
        for j in range(i + 1, n):
            if grouped[j]:
                continue

            if hamming_distance(signatures[i], signatures[j]) <= threshold:
                group.append(j)
                grouped[j] = True

        if len(group) > 1:
            groups.append(group)

    return groups
