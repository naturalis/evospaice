"""Prepare bounded taxonomy partitions from a Parquet and FAISS embedding export."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from .full_scale import (
    ArtifactStore,
    EmbeddingExport,
    FullScaleInputError,
    PartitionManifest,
    PartitionSpec,
    PartitionWorkItem,
    WorkQueue,
    download_json,
    join_object,
    upload_json,
)
from .models import TAXONOMY_RANKS


class VectorIndex(Protocol):
    dimension: int
    record_count: int

    def reconstruct(self, identifiers: NDArray[np.int64]) -> NDArray[np.float32]: ...


@dataclass(frozen=True)
class PrepareConfig:
    source_prefix: str
    run_prefix: str
    bin_mapping_object: str
    trust_policy_object: str
    partition_rank: str = "family"
    max_partition_records: int = 50_000
    record_id_column: str = "record_id"
    bin_column: str = "bin_uri"

    def __post_init__(self) -> None:
        if not self.source_prefix or not self.run_prefix:
            raise ValueError("source and run prefixes cannot be empty")
        if not self.bin_mapping_object or not self.trust_policy_object:
            raise ValueError("BIN mapping and trust policy objects are required")
        if self.partition_rank not in TAXONOMY_RANKS:
            raise ValueError(f"unsupported partition rank: {self.partition_rank}")
        if self.max_partition_records < 2:
            raise ValueError("max partition records must be at least 2")


class FaissVectorIndex:
    def __init__(self, path: Path) -> None:
        try:
            import faiss
        except ImportError as error:
            raise RuntimeError("full-scale preparation requires faiss-cpu") from error
        self._index = faiss.read_index(str(path))
        self.dimension = int(self._index.d)
        self.record_count = int(self._index.ntotal)

    def reconstruct(self, identifiers: NDArray[np.int64]) -> NDArray[np.float32]:
        values = self._index.reconstruct_batch(np.asarray(identifiers, dtype=np.int64))
        return np.asarray(values, dtype=np.float32)


def prepare_partitions(
    source_store: ArtifactStore,
    work_store: ArtifactStore,
    queue: WorkQueue,
    config: PrepareConfig,
    vector_index_factory: Callable[[Path], VectorIndex] = FaissVectorIndex,
) -> PartitionManifest:
    try:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
    except ImportError as error:
        raise RuntimeError("full-scale preparation requires pyarrow") from error

    with tempfile.TemporaryDirectory(prefix="evospaice-prepare-") as temporary_directory:
        work_dir = Path(temporary_directory)
        source_manifest_object = join_object(config.source_prefix, "manifest.json")
        export = EmbeddingExport.from_mapping(download_json(source_store, source_manifest_object))
        metadata_path = work_dir / export.metadata_file
        index_path = work_dir / export.index_file
        mapping_path = work_dir / "record-bin-map.parquet"
        policy_path = work_dir / "trust-policy.json"

        source_store.download(join_object(config.source_prefix, export.metadata_file), metadata_path)
        work_store.download(config.bin_mapping_object, mapping_path)
        work_store.download(config.trust_policy_object, policy_path)

        _verify_sha256(metadata_path, export.metadata_sha256)

        metadata_columns = [export.id_column, config.record_id_column]
        available_columns = set(pq.read_schema(metadata_path).names)
        missing_columns = sorted(set(metadata_columns) - available_columns)
        if missing_columns:
            raise FullScaleInputError(f"metadata is missing columns: {missing_columns}")
        taxonomy_columns = [rank for rank in TAXONOMY_RANKS if rank in available_columns]
        metadata = pq.read_table(metadata_path, columns=metadata_columns + taxonomy_columns)
        for column_index, column_name in enumerate(metadata.column_names):
            if column_name in taxonomy_columns and pa.types.is_null(metadata.schema.field(column_name).type):
                metadata = metadata.set_column(
                    column_index,
                    column_name,
                    metadata[column_name].cast(pa.string()),
                )
        if metadata.num_rows != export.record_count:
            raise FullScaleInputError(
                f"metadata row count {metadata.num_rows} does not match {export.record_count}"
            )
        _require_unique(metadata, export.id_column, pc)
        _require_unique(metadata, config.record_id_column, pc)

        mapping_schema = set(pq.read_schema(mapping_path).names)
        required_mapping = {config.record_id_column, config.bin_column}
        if not required_mapping.issubset(mapping_schema):
            missing = sorted(required_mapping - mapping_schema)
            raise FullScaleInputError(f"BIN mapping is missing columns: {missing}")
        mapping = pq.read_table(mapping_path, columns=sorted(required_mapping))
        _require_unique(mapping, config.record_id_column, pc)
        if mapping[config.bin_column].null_count:
            raise FullScaleInputError("BIN mapping contains null BIN identifiers")
        if mapping.num_rows != metadata.num_rows:
            raise FullScaleInputError("BIN mapping row count must match embedded metadata")

        joined = metadata.join(mapping, keys=config.record_id_column, join_type="inner")
        if joined.num_rows != metadata.num_rows:
            raise FullScaleInputError(
                "BIN mapping must contain exactly one mapping for every embedded record"
            )
        _require_non_empty_strings(joined, config.bin_column, pc)

        selected_ids = joined.group_by(config.bin_column).aggregate(
            [(export.id_column, "min")]
        )
        aggregate_id_column = f"{export.id_column}_min"
        selected_ids = selected_ids.rename_columns(
            [
                export.id_column if name == aggregate_id_column else name
                for name in selected_ids.column_names
            ]
        )
        selected = selected_ids.join(
            joined,
            keys=[config.bin_column, export.id_column],
            join_type="inner",
        )
        selected_leaf_count = selected.num_rows
        if selected_leaf_count == 0:
            raise FullScaleInputError("BIN selection produced no tree leaves")

        source_store.download(join_object(config.source_prefix, export.index_file), index_path)
        _verify_sha256(index_path, export.index_sha256)

        for rank in TAXONOMY_RANKS:
            if rank not in selected.column_names:
                selected = selected.append_column(rank, pa.nulls(selected.num_rows, pa.string()))
        selected_path = work_dir / "selected-records.parquet"
        pq.write_table(selected, selected_path, compression="zstd")
        work_store.upload(
            selected_path,
            join_object(config.run_prefix, "prepare/selected-records.parquet"),
        )

        vector_index = vector_index_factory(index_path)
        if vector_index.dimension != export.dimension:
            raise FullScaleInputError("FAISS vector dimension does not match its manifest")
        if vector_index.record_count != export.record_count:
            raise FullScaleInputError("FAISS record count does not match its manifest")

        partition_rank_index = TAXONOMY_RANKS.index(config.partition_rank)
        partition_ranks = TAXONOMY_RANKS[: partition_rank_index + 1]
        selected_columns = [
            export.id_column,
            config.record_id_column,
            config.bin_column,
            *TAXONOMY_RANKS,
        ]
        selected = selected.select(selected_columns)
        sort_keys = [(rank, "ascending") for rank in partition_ranks]
        sort_keys.append((export.id_column, "ascending"))
        selected = selected.take(pc.sort_indices(selected, sort_keys=sort_keys))

        partitions: list[PartitionSpec] = []
        current_key: tuple[str, ...] | None = None
        current_rows: list[dict[str, object]] = []
        chunk_index = 0

        def flush() -> None:
            nonlocal chunk_index, current_rows
            if current_key is None or not current_rows:
                return
            partition = _write_partition(
                rows=current_rows,
                lineage=current_key,
                chunk_index=chunk_index,
                partition_rank_index=partition_rank_index,
                export=export,
                config=config,
                vector_index=vector_index,
                policy_path=policy_path,
                work_dir=work_dir,
                work_store=work_store,
            )
            partitions.append(partition)
            chunk_index += 1
            current_rows = []

        for batch in selected.to_batches(max_chunksize=min(config.max_partition_records, 65_536)):
            for row in batch.to_pylist():
                key = tuple(str(row.get(rank) or "").strip() for rank in partition_ranks)
                if not any(key):
                    raise FullScaleInputError(
                        f"record {row[config.record_id_column]!r} has no partition taxonomy"
                    )
                if current_key is not None and (
                    key != current_key or len(current_rows) >= config.max_partition_records
                ):
                    flush()
                    if key != current_key:
                        chunk_index = 0
                current_key = key
                current_rows.append(row)
        flush()

        manifest = PartitionManifest(
            run_prefix=config.run_prefix,
            source_prefix=config.source_prefix,
            source_etag=export.source_etag,
            bin_mapping_object=config.bin_mapping_object,
            trust_policy_object=config.trust_policy_object,
            vector_dimension=export.dimension,
            selected_leaf_count=selected_leaf_count,
            partitions=tuple(partitions),
        )
        manifest_object = join_object(config.run_prefix, "prepare/partition-manifest.json")
        upload_json(work_store, manifest_object, manifest.to_mapping())
        upload_json(
            work_store,
            join_object(config.run_prefix, "prepare/validation-report.json"),
            {
                "schema_version": 1,
                "status": "complete",
                "source_record_count": export.record_count,
                "selected_leaf_count": selected_leaf_count,
                "partition_count": len(partitions),
                "partition_rank": config.partition_rank,
                "max_partition_records": config.max_partition_records,
                "bin_mapping_object": config.bin_mapping_object,
            },
        )
        for partition in partitions:
            queue.send(PartitionWorkItem(config.run_prefix, partition).to_json())
        upload_json(
            work_store,
            join_object(config.run_prefix, "prepare/complete.json"),
            {"schema_version": 1, "status": "complete", "partition_count": len(partitions)},
        )
        return manifest


def _write_partition(
    *,
    rows: list[dict[str, object]],
    lineage: tuple[str, ...],
    chunk_index: int,
    partition_rank_index: int,
    export: EmbeddingExport,
    config: PrepareConfig,
    vector_index: VectorIndex,
    policy_path: Path,
    work_dir: Path,
    work_store: ArtifactStore,
) -> PartitionSpec:
    identity = json.dumps([lineage, chunk_index], separators=(",", ":"), ensure_ascii=True)
    partition_id = f"p-{hashlib.sha256(identity.encode()).hexdigest()[:20]}"
    input_prefix = join_object(config.run_prefix, f"prepare/partitions/{partition_id}")
    output_prefix = join_object(config.run_prefix, f"work/subtree-results/{partition_id}")
    partition_dir = work_dir / "partition"
    shutil.rmtree(partition_dir, ignore_errors=True)
    partition_dir.mkdir()

    identifiers = np.asarray([row[export.id_column] for row in rows], dtype=np.int64)
    vectors = vector_index.reconstruct(identifiers)
    if vectors.shape != (len(rows), export.dimension):
        raise FullScaleInputError(f"FAISS returned an invalid vector block for {partition_id}")
    if not np.isfinite(vectors).all():
        raise FullScaleInputError(f"FAISS returned non-finite vectors for {partition_id}")
    norms = np.linalg.norm(vectors, axis=1)
    if not np.allclose(norms, 1.0, rtol=1e-4, atol=1e-5):
        raise FullScaleInputError(f"FAISS returned non-normalized vectors for {partition_id}")
    np.save(partition_dir / "embeddings.npy", vectors, allow_pickle=False)

    records_path = partition_dir / "records.tsv"
    index_path = partition_dir / "embedding-index.tsv"
    record_fields = ["leaf_id", "record_id", "bin_uri", *TAXONOMY_RANKS]
    with records_path.open("w", encoding="utf-8", newline="") as records_handle, index_path.open(
        "w", encoding="utf-8", newline=""
    ) as index_handle:
        record_writer = csv.DictWriter(records_handle, fieldnames=record_fields, delimiter="\t")
        index_writer = csv.DictWriter(
            index_handle, fieldnames=["record_id", "row_index"], delimiter="\t"
        )
        record_writer.writeheader()
        index_writer.writeheader()
        for row_index, row in enumerate(rows):
            record_id = str(row[config.record_id_column])
            bin_uri = str(row[config.bin_column])
            output_row = {
                "leaf_id": bin_uri,
                "record_id": record_id,
                "bin_uri": bin_uri,
                **{
                    rank: str(row.get(rank) or "").strip()
                    if rank_index > partition_rank_index
                    else ""
                    for rank_index, rank in enumerate(TAXONOMY_RANKS)
                },
            }
            record_writer.writerow(output_row)
            index_writer.writerow({"record_id": record_id, "row_index": row_index})

    for path in (records_path, partition_dir / "embeddings.npy", index_path):
        work_store.upload(path, join_object(input_prefix, path.name))
    work_store.upload(policy_path, join_object(input_prefix, "trust-policy.json"))

    taxonomy_path = tuple(
        (rank, name) for rank, name in zip(TAXONOMY_RANKS, lineage, strict=False) if name
    )
    partition = PartitionSpec(
        partition_id=partition_id,
        input_prefix=input_prefix,
        output_prefix=output_prefix,
        taxonomy_path=taxonomy_path,
        leaf_count=len(rows),
    )
    upload_json(
        work_store,
        join_object(input_prefix, "partition.json"),
        partition.to_mapping(),
    )
    return partition


def _verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise FullScaleInputError(f"checksum mismatch for {path.name}")


def _require_unique(table, column: str, compute) -> None:
    if table[column].null_count:
        raise FullScaleInputError(f"{column} contains null values")
    if int(compute.count_distinct(table[column]).as_py()) != table.num_rows:
        raise FullScaleInputError(f"{column} must be unique")


def _require_non_empty_strings(table, column: str, compute) -> None:
    empty_count = int(compute.sum(compute.equal(compute.utf8_trim_whitespace(table[column]), "")).as_py())
    if empty_count:
        raise FullScaleInputError(f"{column} contains empty values")
