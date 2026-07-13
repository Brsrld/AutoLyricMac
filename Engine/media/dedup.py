"""Perceptual deduplication via difference hash (pure, unit-tested)."""


def dhash(image, size=8):
    """64-bit difference hash of a PIL image (row-wise gradient)."""
    gray = image.convert("L").resize((size + 1, size), reducing_gap=2.0)
    pixels = list(gray.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(a, b):
    return bin(a ^ b).count("1")


def is_duplicate(candidate_hash, existing_hashes, threshold=8):
    """True when the hash is within `threshold` bits of any known hash."""
    return any(hamming(candidate_hash, h) <= threshold
               for h in existing_hashes)
