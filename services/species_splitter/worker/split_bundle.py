"""Split a FAISS/Parquet embedding bundle into one bundle per species."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

import faiss
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq
from species import shard_for_key, species_key

LOGGER = logging.getLogger("species_splitter")
PARTITION_BATCH_SIZE = 65_536
VECTOR_BATCH_SIZE = 65_536
PARTITION_PROGRESS_INTERVAL = 250_000
SPECIES_PROGRESS_INTERVAL = 250


def _log_progress(
    stage: str,
    shard_index: int,
    shard_count: int,
    completed: int,
    total: int,
    started_at: float,
    **details: int | float | str,
) -> None:
    elapsed_seconds = max(monotonic() - started_at, 0.001)
    rate_per_second = completed / elapsed_seconds
    remaining = max(total - completed, 0)
    payload = {
        "stage": stage,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "completed": completed,
        "total": total,
        "percent": round(completed / total * 100, 2) if total else 100.0,
        "elapsed_seconds": round(elapsed_seconds, 1),
        "rate_per_second": round(rate_per_second, 2),
        "eta_seconds": round(remaining / rate_per_second, 1) if rate_per_second else None,
        **details,
    }
    LOGGER.info("PROGRESS %s", json.dumps(payload, sort_keys=True))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_bundle(path: Path) -> Path:
    if (path / "index.faiss").is_file():
        return path
    candidates = list(path.rglob("index.faiss"))
    if len(candidates) != 1:
        raise ValueError(f"Expected one embedding bundle under {path}, found {len(candidates)}")
    return candidates[0].parent


def _partition_batches(
    metadata_path: Path,
    shard_index: int,
    shard_count: int,
    started_at: float,
) -> tuple[pa.Schema, Iterator[pa.RecordBatch], dict[str, int]]:
    parquet = pq.ParquetFile(metadata_path)
    output_schema = parquet.schema_arrow.append(pa.field("species_key", pa.string()))
    stats = {"scanned": 0, "selected": 0, "total": parquet.metadata.num_rows}
    key_cache: dict[str | None, str] = {}

    _log_progress(
        "partition",
        shard_index,
        shard_count,
        0,
        stats["total"],
        started_at,
        selected_records=0,
    )

    def batches() -> Iterator[pa.RecordBatch]:
        for batch in parquet.iter_batches(batch_size=PARTITION_BATCH_SIZE):
            species = batch.column(batch.schema.get_field_index("species"))
            encoded = species.dictionary_encode()
            dictionary = encoded.dictionary.to_pylist()
            dictionary_keys = []
            dictionary_shards = []
            for value in dictionary:
                normalized = value.casefold() if value else None
                key = key_cache.setdefault(normalized, species_key(value))
                dictionary_keys.append(key)
                dictionary_shards.append(shard_for_key(key, shard_count))

            keys = pc.take(pa.array(dictionary_keys), encoded.indices)
            keys = pc.fill_null(keys, "unknown")
            shards = pc.take(pa.array(dictionary_shards, type=pa.int32()), encoded.indices)
            unknown_shard = shard_for_key("unknown", shard_count)
            shards = pc.fill_null(shards, unknown_shard)
            mask = pc.equal(shards, shard_index)
            selected_batch = batch.filter(mask)
            selected_keys = keys.filter(mask)
            previous_scanned = stats["scanned"]
            stats["scanned"] += len(batch)
            stats["selected"] += len(selected_batch)
            if (
                stats["scanned"] // PARTITION_PROGRESS_INTERVAL
                > previous_scanned // PARTITION_PROGRESS_INTERVAL
            ):
                _log_progress(
                    "partition",
                    shard_index,
                    shard_count,
                    stats["scanned"],
                    stats["total"],
                    started_at,
                    selected_records=stats["selected"],
                )
            if len(selected_batch):
                yield selected_batch.append_column("species_key", selected_keys)

    return output_schema, batches(), stats


def _partition_metadata(
    metadata_path: Path,
    partition_dir: Path,
    shard_index: int,
    shard_count: int,
) -> int:
    started_at = monotonic()
    schema, batches, stats = _partition_batches(
        metadata_path,
        shard_index,
        shard_count,
        started_at,
    )
    reader = pa.RecordBatchReader.from_batches(schema, batches)
    ds.write_dataset(
        reader,
        base_dir=partition_dir,
        format="parquet",
        partitioning=["species_key"],
        basename_template="part-{i}.parquet",
        existing_data_behavior="delete_matching",
        max_open_files=64,
        max_partitions=PARTITION_BATCH_SIZE,
        max_rows_per_file=PARTITION_BATCH_SIZE,
        min_rows_per_group=PARTITION_BATCH_SIZE,
        max_rows_per_group=PARTITION_BATCH_SIZE,
    )
    _log_progress(
        "partition",
        shard_index,
        shard_count,
        stats["scanned"],
        stats["total"],
        started_at,
        selected_records=stats["selected"],
    )
    return stats["selected"]


def _species_name(table: pa.Table, key: str) -> str | None:
    if key == "unknown":
        return None
    values = [value for value in table.column("species").to_pylist() if value]
    normalized = {value.casefold() for value in values}
    if len(normalized) != 1:
        raise ValueError(f"Species partition {key} contains {len(normalized)} species labels")
    return values[0]


def _write_species_bundle(
    source_index,
    partition_dir: Path,
    output_dir: Path,
    source_manifest: dict,
) -> int:
    key = partition_dir.name
    metadata_path = output_dir / f"{key}.parquet"
    index_path = output_dir / f"{key}.faiss"
    manifest_path = output_dir / f"{key}.json"
    metadata_writer = None
    species_index = faiss.IndexIDMap2(faiss.IndexFlatIP(source_index.d))
    record_count = 0
    canonical_species = None

    try:
        for fragment in sorted(partition_dir.glob("*.parquet")):
            parquet = pq.ParquetFile(fragment)
            for batch in parquet.iter_batches(batch_size=VECTOR_BATCH_SIZE):
                table = pa.Table.from_batches([batch])
                if canonical_species is None:
                    canonical_species = _species_name(table, key)
                ids = table.column("faiss_id").to_numpy(zero_copy_only=False).astype(np.int64)
                vectors = source_index.reconstruct_batch(ids)
                species_index.add_with_ids(vectors, ids)
                if metadata_writer is None:
                    metadata_writer = pq.ParquetWriter(
                        metadata_path,
                        table.schema,
                        compression="zstd",
                    )
                metadata_writer.write_table(table)
                record_count += len(table)
    finally:
        if metadata_writer is not None:
            metadata_writer.close()

    faiss.write_index(species_index, str(index_path))
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "species": canonical_species,
        "species_key": key,
        "source_bundle": source_manifest,
        "index": {
            "file": index_path.name,
            "type": "IndexIDMap2(IndexFlatIP)",
            "metric": "cosine_similarity",
            "normalized": True,
            "dimension": species_index.d,
            "record_count": record_count,
            "sha256": _sha256(index_path),
        },
        "metadata": {
            "file": metadata_path.name,
            "format": "parquet",
            "id_column": "faiss_id",
            "sha256": _sha256(metadata_path),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return record_count


def split_bundle(input_dir: Path, output_dir: Path, shard_index: int, shard_count: int) -> None:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be between zero and shard_count minus one")
    input_dir = _resolve_bundle(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = input_dir / "manifest.json"
    metadata_path = input_dir / "records.parquet"
    index_path = input_dir / "index.faiss"
    for required_path in (manifest_path, metadata_path, index_path):
        if not required_path.is_file():
            raise ValueError(f"Embedding bundle is missing {required_path.name}")

    source_manifest = json.loads(manifest_path.read_text())
    index_started_at = monotonic()
    LOGGER.info(
        "PHASE %s",
        json.dumps(
            {
                "stage": "load_index",
                "shard_index": shard_index,
                "shard_count": shard_count,
                "status": "started",
                "index_size_bytes": index_path.stat().st_size,
            },
            sort_keys=True,
        ),
    )
    source_index = faiss.read_index(str(index_path))
    LOGGER.info(
        "PHASE %s",
        json.dumps(
            {
                "stage": "load_index",
                "shard_index": shard_index,
                "shard_count": shard_count,
                "status": "completed",
                "elapsed_seconds": round(monotonic() - index_started_at, 1),
                "records": source_index.ntotal,
            },
            sort_keys=True,
        ),
    )
    with TemporaryDirectory(prefix="species-partitions-") as temporary_dir:
        partition_dir = Path(temporary_dir)
        selected_records = _partition_metadata(
            metadata_path,
            partition_dir,
            shard_index,
            shard_count,
        )
        total_records = 0
        species_count = 0
        species_dirs = sorted(path for path in partition_dir.iterdir() if path.is_dir())
        species_total = len(species_dirs)
        species_started_at = monotonic()
        _log_progress(
            "write_species",
            shard_index,
            shard_count,
            0,
            species_total,
            species_started_at,
            records_written=0,
        )
        for species_dir in species_dirs:
            total_records += _write_species_bundle(
                source_index,
                species_dir,
                output_dir,
                source_manifest,
            )
            species_count += 1
            if species_count % SPECIES_PROGRESS_INTERVAL == 0:
                _log_progress(
                    "write_species",
                    shard_index,
                    shard_count,
                    species_count,
                    species_total,
                    species_started_at,
                    records_written=total_records,
                )
        _log_progress(
            "write_species",
            shard_index,
            shard_count,
            species_count,
            species_total,
            species_started_at,
            records_written=total_records,
        )

    if total_records != selected_records:
        raise ValueError(
            f"Split {total_records} records but selected {selected_records} metadata rows"
        )
    LOGGER.info(
        "SUMMARY %s",
        json.dumps(
            {
                "shard_index": shard_index,
                "shard_count": shard_count,
                "records": total_records,
                "species_bundles": species_count,
                "status": "completed",
            },
            sort_keys=True,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--shard-index", required=True, type=int)
    parser.add_argument("--shard-count", required=True, type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    split_bundle(**vars(args))


if __name__ == "__main__":
    main()