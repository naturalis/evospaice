"""Reusable validators for the pipeline data contracts.

These check already-parsed structures (column names, manifest dicts, event
payloads) rather than reading files, so they stay dependency-light and easy to
test. They encode the contracts documented in
``docs/architecture/data-contracts.md`` and
``docs/architecture/parquet-metadata-format.md``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from urllib.parse import urlparse

__all__ = [
    "ContractError",
    "REQUIRED_PARQUET_COLUMNS",
    "TAXONOMY_COLUMNS",
    "REQUIRED_MANIFEST_SECTIONS",
    "UNKNOWN_SPECIES_VALUES",
    "is_valid_target_class",
    "validate_parquet_columns",
    "validate_manifest",
    "validate_blob_created_event",
    "normalize_species_label",
]

# Columns every consumer must be able to rely on in records.parquet.
REQUIRED_PARQUET_COLUMNS = (
    "faiss_id",
    "source_record_number",
    "record_id",
    "header",
    "sequence",
    "source_blob_url",
)

# Optional taxonomy columns; missing values are null by contract.
TAXONOMY_COLUMNS = (
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
)

# Top-level sections a global embedding manifest must carry.
REQUIRED_MANIFEST_SECTIONS = ("source", "model", "index", "metadata")

# Species labels that collapse to ``unknown`` (case-insensitive).
UNKNOWN_SPECIES_VALUES = frozenset(
    {"", "none", "unknown", "unidentified", "unclassified", "na", "n/a"}
)

_TARGET_CLASS_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


class ContractError(ValueError):
    """Raised when data violates a documented pipeline contract."""


def is_valid_target_class(value: str) -> bool:
    """Return whether *value* is a legal class-filter ``target_class``."""
    return _TARGET_CLASS_RE.fullmatch(value or "") is not None


def validate_parquet_columns(columns: Iterable[str]) -> None:
    """Raise if any required metadata column is absent from *columns*."""
    present = set(columns)
    missing = [name for name in REQUIRED_PARQUET_COLUMNS if name not in present]
    if missing:
        raise ContractError(
            "records.parquet is missing required columns: " + ", ".join(missing)
        )


def validate_manifest(manifest: Mapping[str, object]) -> None:
    """Raise if a global embedding manifest lacks its required sections."""
    if not isinstance(manifest, Mapping):
        raise ContractError("manifest must be a JSON object")
    missing = [key for key in REQUIRED_MANIFEST_SECTIONS if key not in manifest]
    if missing:
        raise ContractError("manifest is missing required sections: " + ", ".join(missing))
    index = manifest["index"]
    if not isinstance(index, Mapping) or "sha256" not in index or "dimension" not in index:
        raise ContractError("manifest.index must record a dimension and sha256 checksum")
    metadata = manifest["metadata"]
    if not isinstance(metadata, Mapping) or "sha256" not in metadata:
        raise ContractError("manifest.metadata must record a sha256 checksum")


def validate_blob_created_event(
    event: Mapping[str, object],
    *,
    expected_host: str,
    expected_container: str,
    required_suffix: str,
) -> tuple[str, str]:
    """Validate an Event Grid ``BlobCreated`` envelope.

    Returns the ``(url, etag)`` pair on success and raises
    :class:`ContractError` otherwise.
    """
    if not isinstance(event, Mapping):
        raise ContractError("event must be a JSON object")
    if event.get("eventType") != "Microsoft.Storage.BlobCreated":
        raise ContractError("event is not a Microsoft.Storage.BlobCreated event")
    data = event.get("data")
    if not isinstance(data, Mapping):
        raise ContractError("event does not contain a data object")
    url = data.get("url")
    etag = data.get("eTag")
    if not url:
        raise ContractError("event does not contain data.url")
    if not etag:
        raise ContractError("event does not contain data.eTag")
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise ContractError("event came from an unexpected storage account")
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts or path_parts[0] != expected_container:
        raise ContractError("event came from an unexpected container")
    if not parsed.path.endswith(required_suffix):
        raise ContractError(f"blob does not end with {required_suffix!r}")
    return str(url), str(etag)


def normalize_species_label(label: object) -> str | None:
    """Return the trimmed species label, or ``None`` when it means unknown."""
    if label is None:
        return None
    text = str(label).strip()
    if text.casefold() in UNKNOWN_SPECIES_VALUES:
        return None
    return text
