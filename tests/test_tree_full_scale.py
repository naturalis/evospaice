from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from evospaice.tree.full_scale import (
    EmbeddingExport,
    FullScaleInputError,
    PartitionManifest,
    PartitionSpec,
    PartitionWorkItem,
)
from evospaice.tree.full_scale_finalize import _graft_partition_trees
from evospaice.tree.full_scale_prepare import PrepareConfig, prepare_partitions


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

    def send(self, content: str) -> None:
        self.messages.append(content)


class FakeVectorIndex:
    dimension = 2
    record_count = 4

    def reconstruct(self, identifiers: np.ndarray) -> np.ndarray:
        vectors = {
            0: (1.0, 0.0),
            1: (0.0, 1.0),
            2: (2**-0.5, 2**-0.5),
            3: (-1.0, 0.0),
        }
        return np.asarray([vectors[int(identifier)] for identifier in identifiers], dtype=np.float32)


def test_production_embedding_manifest_contract() -> None:
    export = EmbeddingExport.from_mapping(
        {
            "schema_version": 1,
            "source": {"etag": "0x8df1258ad040f84", "size_bytes": 3279290758},
            "index": {
                "type": "IndexIDMap2(IndexFlatIP)",
                "metric": "cosine_similarity",
                "normalized": True,
                "dimension": 256,
                "record_count": 6979067,
                "file": "index.faiss",
                "sha256": "3ba3e988e1333ebb54f6e91af0605e3ee8532c9a0ff568a2c5350896f87c512e",
            },
            "metadata": {
                "format": "parquet",
                "file": "records.parquet",
                "sha256": "b711aa75cfcba769de416b2e545e68ee51710d9f81dbb2bb56a38e95d7d4a2c3",
                "id_column": "faiss_id",
            },
        }
    )

    assert export.record_count == 6_979_067
    assert export.dimension == 256
    assert export.metadata_file == "records.parquet"


def test_prepare_selects_one_record_per_bin_and_enqueues_bounded_partitions(
    tmp_path: Path,
) -> None:
    metadata_path = tmp_path / "records.parquet"
    mapping_path = tmp_path / "record-bin-map.parquet"
    index_path = tmp_path / "index.faiss"
    policy_path = tmp_path / "trust-policy.json"
    pq.write_table(
        pa.table(
            {
                "faiss_id": [0, 1, 2, 3],
                "record_id": ["r0", "r1", "r2", "r3"],
                "kingdom": pa.nulls(4),
                "phylum": ["Arthropoda"] * 4,
                "class": ["Insecta"] * 4,
                "order": ["Diptera", "Diptera", "Diptera", "Coleoptera"],
                "family": ["F1", "F1", "F2", "F3"],
                "genus": ["G1", "G1", "G2", "G3"],
            }
        ),
        metadata_path,
    )
    pq.write_table(
        pa.table(
            {
                "record_id": ["r0", "r1", "r2", "r3"],
                "bin_uri": ["BOLD:A", "BOLD:A", "BOLD:B", "BOLD:C"],
            }
        ),
        mapping_path,
    )
    index_path.write_bytes(b"fake-index")
    policy_path.write_text('{"version": "test"}\n', encoding="utf-8")

    source_manifest = {
        "schema_version": 1,
        "source": {"etag": "etag", "size_bytes": 100},
        "index": {
            "type": "IndexIDMap2(IndexFlatIP)",
            "metric": "cosine_similarity",
            "normalized": True,
            "dimension": 2,
            "record_count": 4,
            "file": index_path.name,
            "sha256": _sha256(index_path),
        },
        "metadata": {
            "file": metadata_path.name,
            "sha256": _sha256(metadata_path),
            "id_column": "faiss_id",
        },
    }
    source_store = MemoryStore(
        {
            "source/manifest.json": json.dumps(source_manifest).encode(),
            "source/records.parquet": metadata_path.read_bytes(),
            "source/index.faiss": index_path.read_bytes(),
        }
    )
    work_store = MemoryStore(
        {
            "runs/test/input/record-bin-map.parquet": mapping_path.read_bytes(),
            "runs/test/input/trust-policy.json": policy_path.read_bytes(),
        }
    )
    queue = MemoryQueue()

    result = prepare_partitions(
        source_store,
        work_store,
        queue,
        PrepareConfig(
            source_prefix="source",
            run_prefix="runs/test",
            bin_mapping_object="runs/test/input/record-bin-map.parquet",
            trust_policy_object="runs/test/input/trust-policy.json",
            max_partition_records=2,
        ),
        vector_index_factory=lambda _: FakeVectorIndex(),
    )

    assert result.selected_leaf_count == 3
    assert sum(partition.leaf_count for partition in result.partitions) == 3
    assert len(queue.messages) == len(result.partitions)
    assert "runs/test/prepare/partition-manifest.json" in work_store.objects
    assert "runs/test/prepare/complete.json" in work_store.objects
    assert PartitionManifest.from_mapping(
        json.loads(work_store.objects["runs/test/prepare/partition-manifest.json"])
    ) == result
    work_items = [PartitionWorkItem.from_json(message) for message in queue.messages]
    assert {item.partition.partition_id for item in work_items} == {
        partition.partition_id for partition in result.partitions
    }
    generated_records = "\n".join(
        work_store.objects[f"{partition.input_prefix}/records.tsv"].decode()
        for partition in result.partitions
    )
    assert generated_records.count("BOLD:A") == 1


def test_partition_manifest_rejects_inconsistent_leaf_total() -> None:
    with pytest.raises(FullScaleInputError, match="leaf counts"):
        PartitionManifest.from_mapping(
            {
                "schema_version": 1,
                "run_prefix": "runs/test",
                "source_prefix": "source",
                "source_etag": "etag",
                "bin_mapping_object": "runs/test/input/map.parquet",
                "trust_policy_object": "runs/test/input/policy.json",
                "vector_dimension": 2,
                "selected_leaf_count": 2,
                "partition_count": 1,
                "partitions": [
                    {
                        "partition_id": "p-one",
                        "input_prefix": "runs/test/prepare/partitions/p-one",
                        "output_prefix": "runs/test/work/subtree-results/p-one",
                        "taxonomy_path": [["kingdom", "Animalia"]],
                        "leaf_count": 1,
                    }
                ],
            }
        )


def test_finalize_grafts_worker_clade_at_partition_leaf(tmp_path: Path) -> None:
    partition = PartitionSpec(
        partition_id="p-one",
        input_prefix="runs/test/prepare/partitions/p-one",
        output_prefix="runs/test/work/subtree-results/p-one",
        taxonomy_path=(("kingdom", "Animalia"), ("family", "Testidae")),
        leaf_count=2,
    )
    worker_directory = tmp_path / partition.partition_id
    worker_directory.mkdir()
    (worker_directory / "scaled-tree.nwk").write_text(
        "('BOLD:A':0.1,'BOLD:B':0.2)root;\n",
        encoding="utf-8",
    )

    combined = _graft_partition_trees(
        "(partition_p-one:0.3)root;\n",
        (partition,),
        tmp_path,
    )

    assert "partition_p-one" not in combined
    assert combined == "(('BOLD:A':0.1,'BOLD:B':0.2):0.3)root;\n"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
