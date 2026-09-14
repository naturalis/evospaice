"""Partitioned full-scale tree workflow contracts and Azure job stages."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import TAXONOMY_RANKS


class FullScaleInputError(ValueError):
    """Raised when a full-scale artifact violates its declared contract."""


class ArtifactStore(Protocol):
    def download(self, object_name: str, destination: Path) -> None: ...

    def upload(self, source: Path, object_name: str) -> None: ...


@dataclass(frozen=True)
class QueueLease:
    content: str
    message_id: str
    pop_receipt: str
    dequeue_count: int


class WorkQueue(Protocol):
    def send(self, content: str) -> None: ...

    def receive(self) -> QueueLease | None: ...

    def delete(self, lease: QueueLease) -> None: ...

    def move_to_poison(self, lease: QueueLease, reason: str) -> None: ...


@dataclass(frozen=True)
class EmbeddingExport:
    source_etag: str
    source_size_bytes: int
    index_file: str
    index_sha256: str
    index_type: str
    metric: str
    normalized: bool
    dimension: int
    record_count: int
    metadata_file: str
    metadata_sha256: str
    id_column: str

    @classmethod
    def from_path(cls, path: Path) -> EmbeddingExport:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise FullScaleInputError("embedding manifest must be a JSON object")
        return cls.from_mapping(value)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> EmbeddingExport:
        try:
            schema_version = value["schema_version"]
            source = value["source"]
            index = value["index"]
            metadata = value["metadata"]
            export = cls(
                source_etag=str(source["etag"]),
                source_size_bytes=int(source["size_bytes"]),
                index_file=str(index["file"]),
                index_sha256=str(index["sha256"]),
                index_type=str(index["type"]),
                metric=str(index["metric"]),
                normalized=bool(index["normalized"]),
                dimension=int(index["dimension"]),
                record_count=int(index["record_count"]),
                metadata_file=str(metadata["file"]),
                metadata_sha256=str(metadata["sha256"]),
                id_column=str(metadata["id_column"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FullScaleInputError(f"invalid embedding manifest: {error}") from error

        if schema_version != 1:
            raise FullScaleInputError(f"unsupported embedding schema version: {schema_version}")
        if export.source_size_bytes <= 0:
            raise FullScaleInputError("source size must be positive")
        if export.record_count <= 0 or export.dimension <= 0:
            raise FullScaleInputError("record count and vector dimension must be positive")
        if export.metric != "cosine_similarity" or not export.normalized:
            raise FullScaleInputError(
                "full-scale tree building requires normalized cosine-similarity vectors"
            )
        if not export.index_type.startswith("IndexIDMap2(IndexFlatIP"):
            raise FullScaleInputError("FAISS export must be an ID-mapped exact inner-product index")
        for name, digest in (
            (export.index_file, export.index_sha256),
            (export.metadata_file, export.metadata_sha256),
        ):
            if Path(name).name != name:
                raise FullScaleInputError(f"manifest artifact must be a filename: {name!r}")
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise FullScaleInputError(f"invalid SHA-256 for {name}")
        if not export.id_column:
            raise FullScaleInputError("metadata ID column cannot be empty")
        return export


@dataclass(frozen=True)
class PartitionSpec:
    partition_id: str
    input_prefix: str
    output_prefix: str
    taxonomy_path: tuple[tuple[str, str], ...]
    leaf_count: int

    def __post_init__(self) -> None:
        if not self.partition_id or not self.input_prefix or not self.output_prefix:
            raise FullScaleInputError("partition ID and prefixes cannot be empty")
        if self.leaf_count <= 0:
            raise FullScaleInputError("partition leaf count must be positive")
        ranks = [rank for rank, name in self.taxonomy_path if name]
        if not ranks or any(rank not in TAXONOMY_RANKS for rank in ranks):
            raise FullScaleInputError("partition requires a valid non-empty taxonomy path")
        positions = [TAXONOMY_RANKS.index(rank) for rank in ranks]
        if positions != sorted(set(positions)):
            raise FullScaleInputError("partition taxonomy ranks must be unique and ordered")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "partition_id": self.partition_id,
            "input_prefix": self.input_prefix,
            "output_prefix": self.output_prefix,
            "taxonomy_path": [list(item) for item in self.taxonomy_path],
            "leaf_count": self.leaf_count,
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PartitionSpec:
        try:
            taxonomy_path = tuple((str(rank), str(name)) for rank, name in value["taxonomy_path"])
            return cls(
                partition_id=str(value["partition_id"]),
                input_prefix=str(value["input_prefix"]),
                output_prefix=str(value["output_prefix"]),
                taxonomy_path=taxonomy_path,
                leaf_count=int(value["leaf_count"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FullScaleInputError(f"invalid partition specification: {error}") from error


@dataclass(frozen=True)
class PartitionManifest:
    run_prefix: str
    source_prefix: str
    source_etag: str
    bin_mapping_object: str
    trust_policy_object: str
    vector_dimension: int
    selected_leaf_count: int
    partitions: tuple[PartitionSpec, ...]

    def __post_init__(self) -> None:
        if not all(
            (
                self.run_prefix,
                self.source_prefix,
                self.source_etag,
                self.bin_mapping_object,
                self.trust_policy_object,
            )
        ):
            raise FullScaleInputError("run and source identity cannot be empty")
        if self.vector_dimension <= 0 or self.selected_leaf_count <= 0:
            raise FullScaleInputError("manifest counts must be positive")
        if not self.partitions:
            raise FullScaleInputError("partition manifest cannot be empty")
        partition_ids = [partition.partition_id for partition in self.partitions]
        if len(partition_ids) != len(set(partition_ids)):
            raise FullScaleInputError("partition IDs must be unique")
        if sum(partition.leaf_count for partition in self.partitions) != self.selected_leaf_count:
            raise FullScaleInputError("partition leaf counts do not match selected leaf count")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_prefix": self.run_prefix,
            "source_prefix": self.source_prefix,
            "source_etag": self.source_etag,
            "bin_mapping_object": self.bin_mapping_object,
            "trust_policy_object": self.trust_policy_object,
            "vector_dimension": self.vector_dimension,
            "selected_leaf_count": self.selected_leaf_count,
            "partition_count": len(self.partitions),
            "partitions": [partition.to_mapping() for partition in self.partitions],
        }

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PartitionManifest:
        try:
            if value["schema_version"] != 1:
                raise FullScaleInputError(
                    f"unsupported partition schema version: {value['schema_version']}"
                )
            partitions = tuple(
                PartitionSpec.from_mapping(item) for item in value["partitions"]
            )
            manifest = cls(
                run_prefix=str(value["run_prefix"]),
                source_prefix=str(value["source_prefix"]),
                source_etag=str(value["source_etag"]),
                bin_mapping_object=str(value["bin_mapping_object"]),
                trust_policy_object=str(value["trust_policy_object"]),
                vector_dimension=int(value["vector_dimension"]),
                selected_leaf_count=int(value["selected_leaf_count"]),
                partitions=partitions,
            )
            if int(value["partition_count"]) != len(partitions):
                raise FullScaleInputError("declared partition count does not match partitions")
            return manifest
        except FullScaleInputError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise FullScaleInputError(f"invalid partition manifest: {error}") from error


@dataclass(frozen=True)
class PartitionWorkItem:
    run_prefix: str
    partition: PartitionSpec

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": 1,
                "run_prefix": self.run_prefix,
                "partition": self.partition.to_mapping(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, content: str) -> PartitionWorkItem:
        try:
            value = json.loads(content)
            if not isinstance(value, dict) or value.get("schema_version") != 1:
                raise FullScaleInputError("unsupported partition work-item schema")
            return cls(
                run_prefix=str(value["run_prefix"]),
                partition=PartitionSpec.from_mapping(value["partition"]),
            )
        except FullScaleInputError:
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise FullScaleInputError(f"invalid partition work item: {error}") from error


def download_json(store: ArtifactStore, object_name: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="evospaice-json-") as temporary_directory:
        path = Path(temporary_directory) / "artifact.json"
        store.download(object_name, path)
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    if not isinstance(value, dict):
        raise FullScaleInputError(f"{object_name} must contain a JSON object")
    return value


def upload_json(store: ArtifactStore, object_name: str, value: dict[str, Any]) -> None:
    with tempfile.TemporaryDirectory(prefix="evospaice-json-") as temporary_directory:
        path = Path(temporary_directory) / "artifact.json"
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        store.upload(path, object_name)


def join_object(prefix: str, name: str) -> str:
    return f"{prefix.strip('/')}/{name.lstrip('/')}"
