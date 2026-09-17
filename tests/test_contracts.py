"""Tests for the reusable data-contract validators."""

from __future__ import annotations

import pytest

from evospaice.contracts import (
    REQUIRED_PARQUET_COLUMNS,
    ContractError,
    is_valid_target_class,
    normalize_species_label,
    validate_blob_created_event,
    validate_manifest,
    validate_parquet_columns,
)


def _valid_event() -> dict:
    return {
        "eventType": "Microsoft.Storage.BlobCreated",
        "data": {
            "url": "https://acct.blob.core.windows.net/filtered-sequences/insecta.fasta",
            "eTag": "0x8DF1258AD040F84",
        },
    }


def _valid_manifest() -> dict:
    return {
        "source": {"blob_url": "https://acct.blob.core.windows.net/c/x.fasta", "etag": "e"},
        "model": {"id": "zehui127/Omni-DNA-20M"},
        "index": {"dimension": 256, "sha256": "a" * 64},
        "metadata": {"sha256": "b" * 64},
    }


class TestParquetColumns:
    def test_accepts_all_required_columns(self):
        validate_parquet_columns(REQUIRED_PARQUET_COLUMNS)

    def test_rejects_missing_column(self):
        columns = [c for c in REQUIRED_PARQUET_COLUMNS if c != "faiss_id"]
        with pytest.raises(ContractError, match="faiss_id"):
            validate_parquet_columns(columns)


class TestManifest:
    def test_accepts_valid_manifest(self):
        validate_manifest(_valid_manifest())

    def test_rejects_missing_section(self):
        manifest = _valid_manifest()
        del manifest["model"]
        with pytest.raises(ContractError, match="model"):
            validate_manifest(manifest)

    def test_rejects_index_without_checksum(self):
        manifest = _valid_manifest()
        manifest["index"] = {"dimension": 256}
        with pytest.raises(ContractError, match="sha256"):
            validate_manifest(manifest)


class TestBlobCreatedEvent:
    def test_returns_url_and_etag(self):
        url, etag = validate_blob_created_event(
            _valid_event(),
            expected_host="acct.blob.core.windows.net",
            expected_container="filtered-sequences",
            required_suffix=".fasta",
        )
        assert url.endswith("insecta.fasta")
        assert etag == "0x8DF1258AD040F84"

    def test_rejects_wrong_host(self):
        with pytest.raises(ContractError, match="storage account"):
            validate_blob_created_event(
                _valid_event(),
                expected_host="other.blob.core.windows.net",
                expected_container="filtered-sequences",
                required_suffix=".fasta",
            )

    def test_rejects_wrong_container(self):
        with pytest.raises(ContractError, match="container"):
            validate_blob_created_event(
                _valid_event(),
                expected_host="acct.blob.core.windows.net",
                expected_container="other-container",
                required_suffix=".fasta",
            )

    def test_rejects_wrong_suffix(self):
        with pytest.raises(ContractError, match="faiss"):
            validate_blob_created_event(
                _valid_event(),
                expected_host="acct.blob.core.windows.net",
                expected_container="filtered-sequences",
                required_suffix=".faiss",
            )

    def test_rejects_non_blobcreated_event(self):
        event = _valid_event()
        event["eventType"] = "Microsoft.Storage.BlobDeleted"
        with pytest.raises(ContractError, match="BlobCreated"):
            validate_blob_created_event(
                event,
                expected_host="acct.blob.core.windows.net",
                expected_container="filtered-sequences",
                required_suffix=".fasta",
            )


class TestSpeciesLabel:
    @pytest.mark.parametrize("value", ["", "  ", "unknown", "N/A", "Unidentified", None])
    def test_unknown_values_map_to_none(self, value):
        assert normalize_species_label(value) is None

    def test_known_value_is_trimmed(self):
        assert normalize_species_label("  Danaus plexippus  ") == "Danaus plexippus"


class TestTargetClass:
    @pytest.mark.parametrize("value", ["Insecta", "Class_1", "a-b"])
    def test_valid(self, value):
        assert is_valid_target_class(value)

    @pytest.mark.parametrize("value", ["", "1Insecta", "has space", "bad!"])
    def test_invalid(self, value):
        assert not is_valid_target_class(value)
