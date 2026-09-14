"""Stable species file naming."""

from __future__ import annotations

import hashlib
import re

_UNSAFE = re.compile(r"[^a-z0-9]+")
_UNKNOWN = {"", "none", "unknown", "unidentified", "unclassified", "na", "n/a"}


def species_key(species: str | None) -> str:
    normalized = (species or "").strip()
    if normalized.casefold() in _UNKNOWN:
        return "unknown"
    slug = _UNSAFE.sub("-", normalized.casefold()).strip("-")[:80] or "species"
    fingerprint = hashlib.sha256(normalized.casefold().encode()).hexdigest()[:10]
    return f"{slug}-{fingerprint}"


def shard_for_key(key: str, shard_count: int) -> int:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], "big") % shard_count