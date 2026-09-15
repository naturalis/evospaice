from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import faiss
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from evospaice.tree.full_scale import QueueLease
from evospaice.tree.full_scale_finalize import FinalizeConfig, finalize_partitions
from evospaice.tree.full_scale_prepare import PrepareConfig, prepare_partitions
from evospaice.tree.full_scale_worker import run_partition_worker
from evospaice.tree.models import TAXONOMY_RANKS, TreeBuildConfig

REPOSITORY_ROOT = Path(__file__).parents[1]
SMOKE_DATA = REPOSITORY_ROOT / "data" / "full-scale-smoke"
VECTOR_DIMENSION = 256
MAX_PARTITION_RECORDS = 3


class MemoryStore:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = dict(objects or {})

    def download(self, object_name: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[object_name])

    def upload(self, source: Path, object_name: str) -> None:
        content = source.read_bytes()
        existing = self.objects.get(object_name)
        if existing is not None and existing != content:
            raise RuntimeError(f"immutable object differs: {object_name}")
        self.objects[object_name] = content


class MemoryQueue:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.deleted: list[str] = []
        self.poisoned: list[str] = []
        self._next_message_id = 0

    def send(self, content: str) -> None:
        self.messages.append(content)

    def receive(self) -> QueueLease | None:
        if not self.messages:
            return None
        self._next_message_id += 1
        return QueueLease(
            content=self.messages.pop(0),
            message_id=f"message-{self._next_message_id}",
            pop_receipt=f"receipt-{self._next_message_id}",
            dequeue_count=1,
        )

    def delete(self, lease: QueueLease) -> None:
        self.deleted.append(lease.message_id)

    def move_to_poison(self, lease: QueueLease, reason: str) -> None:
        self.poisoned.append(f"{lease.message_id}: {reason}")


def _read_source_rows() -> list[dict[str, str]]:
    with (SMOKE_DATA / "records.tsv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _taxonomy_vectors(rows: list[dict[str, str]]) -> np.ndarray:
    vectors = np.zeros((len(rows), VECTOR_DIMENSION), dtype=np.float32)
    dimensions = {
        "order": 1,
        "family": 16,
        "subfamily": 32,
        "tribe": 48,
        "genus": 64,
        "species": 96,
    }
    weights = {
        "order": 0.45,
        "family": 0.7,
        "subfamily": 0.55,
        "tribe": 0.5,
        "genus": 0.8,
        "species": 0.35,
    }
    vectors[:, 0] = 1.0
    for rank, start_dimension in dimensions.items():
        names = sorted({row[rank] for row in rows if row[rank]})
        dimension_by_name = {
            name: start_dimension + index for index, name in enumerate(names)
        }
        for row_index, row in enumerate(rows):
            if row[rank]:
                vectors[row_index, dimension_by_name[row[rank]]] = weights[rank]
    for row_index in range(len(rows)):
        vectors[row_index, 160 + row_index] = 0.05
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_production_inputs(tmp_path: Path) -> tuple[MemoryStore, MemoryStore]:
    rows = _read_source_rows()
    source_directory = tmp_path / "source"
    source_directory.mkdir()
    metadata_path = source_directory / "records.parquet"
    index_path = source_directory / "index.faiss"
    mapping_path = tmp_path / "record-bin-map.parquet"

    metadata = {
        "faiss_id": pa.array([int(row["faiss_id"]) for row in rows], pa.int64()),
        "record_id": [row["record_id"] for row in rows],
        **{rank: [row[rank] or None for row in rows] for rank in TAXONOMY_RANKS},
    }
    pq.write_table(pa.table(metadata), metadata_path, compression="zstd")
    pq.write_table(
        pa.table(
            {
                "record_id": [row["record_id"] for row in rows],
                "bin_uri": [row["bin_uri"] for row in rows],
            }
        ),
        mapping_path,
        compression="zstd",
    )

    vectors = _taxonomy_vectors(rows)
    index = faiss.IndexIDMap2(faiss.IndexFlatIP(VECTOR_DIMENSION))
    index.add_with_ids(vectors, np.arange(len(rows), dtype=np.int64))
    faiss.write_index(index, str(index_path))

    manifest = {
        "schema_version": 1,
        "source": {
            "etag": "representative-full-scale-smoke-v1",
            "size_bytes": (SMOKE_DATA / "records.tsv").stat().st_size,
        },
        "index": {
            "type": "IndexIDMap2(IndexFlatIP)",
            "metric": "cosine_similarity",
            "normalized": True,
            "dimension": VECTOR_DIMENSION,
            "record_count": len(rows),
            "file": index_path.name,
            "sha256": _sha256(index_path),
        },
        "metadata": {
            "format": "parquet",
            "file": metadata_path.name,
            "sha256": _sha256(metadata_path),
            "id_column": "faiss_id",
        },
    }
    source_store = MemoryStore(
        {
            "source/manifest.json": json.dumps(manifest).encode(),
            "source/records.parquet": metadata_path.read_bytes(),
            "source/index.faiss": index_path.read_bytes(),
        }
    )
    work_store = MemoryStore(
        {
            "runs/smoke/input/record-bin-map.parquet": mapping_path.read_bytes(),
            "runs/smoke/input/trust-policy.json": (
                SMOKE_DATA / "trust-policy.json"
            ).read_bytes(),
        }
    )
    return source_store, work_store


def _partition_rows(store: MemoryStore, input_prefix: str) -> list[dict[str, str]]:
    content = store.objects[f"{input_prefix}/records.tsv"].decode().splitlines()
    return list(csv.DictReader(content, delimiter="\t"))


def test_representative_full_scale_smoke(tmp_path: Path) -> None:
    source_store, work_store = _build_production_inputs(tmp_path)
    queue = MemoryQueue()
    manifest = prepare_partitions(
        source_store,
        work_store,
        queue,
        PrepareConfig(
            source_prefix="source",
            run_prefix="runs/smoke",
            bin_mapping_object="runs/smoke/input/record-bin-map.parquet",
            trust_policy_object="runs/smoke/input/trust-policy.json",
            partition_rank="family",
            max_partition_records=MAX_PARTITION_RECORDS,
        ),
    )

    assert manifest.selected_leaf_count == 12
    assert len(manifest.partitions) == 5
    assert all(
        partition.leaf_count <= MAX_PARTITION_RECORDS
        for partition in manifest.partitions
    )

    source_genus_by_bin = {
        row["bin_uri"]: row["genus"]
        for row in _read_source_rows()
        if int(row["faiss_id"]) < 12
    }
    partitions_by_genus: dict[str, set[str]] = defaultdict(set)
    selected_bins: list[str] = []
    for partition in manifest.partitions:
        for row in _partition_rows(work_store, partition.input_prefix):
            selected_bins.append(row["bin_uri"])
            partitions_by_genus[source_genus_by_bin[row["bin_uri"]]].add(
                partition.partition_id
            )
    assert len(selected_bins) == len(set(selected_bins)) == 12
    assert all(len(partition_ids) == 1 for partition_ids in partitions_by_genus.values())

    processed_partitions = []
    while queue.messages:
        partition_id = run_partition_worker(
            work_store,
            queue,
            tree_config=TreeBuildConfig(max_nj_children=8),
        )
        assert partition_id is not None
        processed_partitions.append(partition_id)
    assert len(processed_partitions) == len(manifest.partitions)
    assert not queue.poisoned
    shallow_partition = next(
        partition
        for partition in manifest.partitions
        if any(
            row["bin_uri"] == "BOLD:SMOKE-PIE-1"
            for row in _partition_rows(work_store, partition.input_prefix)
        )
    )
    shallow_diagnostics = list(
        csv.DictReader(
            work_store.objects[
                f"{shallow_partition.output_prefix}/node-diagnostics.tsv"
            ].decode().splitlines(),
            delimiter="\t",
        )
    )
    shallow_root = next(
        row for row in shallow_diagnostics if row["node_id"] == "taxonomy:root"
    )
    assert shallow_root["rank"] == "family"
    assert shallow_root["child_count"] == "1"

    result = finalize_partitions(
        work_store,
        FinalizeConfig(run_prefix="runs/smoke", output_prefix="results/smoke"),
        TreeBuildConfig(max_nj_children=8),
    )
    assert result.leaf_count == 12
    assert result.partition_count == 5

    final_tree = work_store.objects["results/smoke/scaled-tree.nwk"].decode()
    assert final_tree.endswith(";\n")
    assert all(final_tree.count(bin_uri) == 1 for bin_uri in selected_bins)
    diagnostics = work_store.objects["results/smoke/node-diagnostics.tsv"].decode()
    assert "neighbor_joining" in diagnostics
    final_manifest = json.loads(
        work_store.objects["results/smoke/tree-manifest.json"]
    )
    assert final_manifest["status"] == "complete"
    assert final_manifest["counts"] == {"leaves": 12, "partitions": 5}