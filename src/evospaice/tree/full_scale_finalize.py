"""Reduce completed partition trees and publish one immutable full-scale tree."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .full_scale import (
    ArtifactStore,
    FullScaleInputError,
    PartitionManifest,
    PartitionSpec,
    download_json,
    join_object,
    upload_json,
)
from .models import InputPaths, TAXONOMY_RANKS, TreeBuildConfig
from .pipeline import build_tree


@dataclass(frozen=True)
class FinalizeConfig:
    run_prefix: str
    output_prefix: str

    def __post_init__(self) -> None:
        if not self.run_prefix or not self.output_prefix:
            raise ValueError("run and output prefixes cannot be empty")


@dataclass(frozen=True)
class FinalizeResult:
    output_prefix: str
    leaf_count: int
    partition_count: int


def finalize_partitions(
    store: ArtifactStore,
    config: FinalizeConfig,
    tree_config: TreeBuildConfig | None = None,
) -> FinalizeResult:
    manifest_object = join_object(config.run_prefix, "prepare/partition-manifest.json")
    partition_manifest = PartitionManifest.from_mapping(download_json(store, manifest_object))
    if partition_manifest.run_prefix != config.run_prefix:
        raise FullScaleInputError("partition manifest belongs to a different run")

    selected_tree_config = tree_config or TreeBuildConfig()
    with tempfile.TemporaryDirectory(prefix="evospaice-finalize-") as temporary_directory:
        work_dir = Path(temporary_directory)
        partition_dir = work_dir / "partitions"
        partition_dir.mkdir()
        partition_manifests: dict[str, dict[str, object]] = {}

        for partition in partition_manifest.partitions:
            completion = download_json(
                store,
                join_object(
                    config.run_prefix,
                    f"work/completion/{partition.partition_id}.json",
                ),
            )
            if completion.get("status") != "complete":
                raise FullScaleInputError(f"partition is not complete: {partition.partition_id}")
            if completion.get("partition_id") != partition.partition_id:
                raise FullScaleInputError(
                    f"completion marker does not match {partition.partition_id}"
                )
            if int(completion.get("leaf_count", -1)) != partition.leaf_count:
                raise FullScaleInputError(
                    f"completion leaf count does not match {partition.partition_id}"
                )

            output_dir = partition_dir / partition.partition_id
            output_dir.mkdir()
            for name in (
                "scaled-tree.nwk",
                "root-representative.npy",
                "node-diagnostics.tsv",
                "excluded-records.tsv",
                "tree-manifest.json",
            ):
                store.download(join_object(partition.output_prefix, name), output_dir / name)
            worker_manifest = json.loads(
                (output_dir / "tree-manifest.json").read_text(encoding="utf-8")
            )
            if worker_manifest.get("status") != "complete":
                raise FullScaleInputError(
                    f"worker manifest is not complete: {partition.partition_id}"
                )
            worker_leaf_count = int(worker_manifest.get("counts", {}).get("leaves", -1))
            if worker_leaf_count != partition.leaf_count:
                raise FullScaleInputError(
                    f"worker leaf count does not match {partition.partition_id}"
                )
            _verify_declared_outputs(output_dir, worker_manifest, partition.partition_id)
            partition_manifests[partition.partition_id] = worker_manifest

        upper_input = work_dir / "upper-input"
        upper_output = work_dir / "upper-output"
        upper_input.mkdir()
        _write_upper_inputs(
            partition_manifest,
            partition_dir,
            upper_input,
            store,
        )
        upper_result = build_tree(
            InputPaths(
                records=upper_input / "records.tsv",
                embeddings=upper_input / "embeddings.npy",
                embedding_index=upper_input / "embedding-index.tsv",
                trust_policy=upper_input / "trust-policy.json",
                output_dir=upper_output,
            ),
            selected_tree_config,
        )
        if upper_result.leaf_count != len(partition_manifest.partitions):
            raise FullScaleInputError("upper tree does not contain every partition")

        final_dir = work_dir / "final"
        final_dir.mkdir()
        final_tree = final_dir / "scaled-tree.nwk"
        final_tree.write_text(
            _graft_partition_trees(
                upper_result.tree_path.read_text(encoding="utf-8"),
                partition_manifest.partitions,
                partition_dir,
            ),
            encoding="utf-8",
        )
        _validate_final_tree(final_tree, partition_manifest.selected_leaf_count)
        _merge_tabular_outputs(
            upper_output / "node-diagnostics.tsv",
            partition_manifest.partitions,
            partition_dir,
            "node-diagnostics.tsv",
            final_dir / "node-diagnostics.tsv",
        )
        _merge_tabular_outputs(
            upper_output / "excluded-records.tsv",
            partition_manifest.partitions,
            partition_dir,
            "excluded-records.tsv",
            final_dir / "excluded-records.tsv",
        )
        root_representative = final_dir / "root-representative.npy"
        root_representative.write_bytes(
            (upper_output / "root-representative.npy").read_bytes()
        )
        upload_json(
            _LocalDirectoryStore(final_dir),
            "validation-report.json",
            {
                "schema_version": 1,
                "status": "complete",
                "expected_leaves": partition_manifest.selected_leaf_count,
                "partition_leaf_total": sum(
                    partition.leaf_count for partition in partition_manifest.partitions
                ),
                "partition_count": len(partition_manifest.partitions),
            },
        )
        checkpoint_dir = final_dir / "checkpoints"
        checkpoint_dir.mkdir()
        (checkpoint_dir / "complete.json").write_text(
            json.dumps(
                {
                    "status": "complete",
                    "processed_partitions": len(partition_manifest.partitions),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        output_files = [
            final_tree,
            final_dir / "node-diagnostics.tsv",
            final_dir / "excluded-records.tsv",
            root_representative,
            final_dir / "validation-report.json",
            checkpoint_dir / "complete.json",
        ]
        final_manifest = {
            "schema_version": 1,
            "status": "complete",
            "source": {
                "prefix": partition_manifest.source_prefix,
                "etag": partition_manifest.source_etag,
            },
            "partition_manifest": manifest_object,
            "config": asdict(selected_tree_config),
            "counts": {
                "leaves": partition_manifest.selected_leaf_count,
                "partitions": len(partition_manifest.partitions),
            },
            "partition_manifests": {
                partition_id: hashlib.sha256(
                    json.dumps(value, sort_keys=True).encode("utf-8")
                ).hexdigest()
                for partition_id, value in sorted(partition_manifests.items())
            },
            "outputs": {
                path.relative_to(final_dir).as_posix(): _sha256(path) for path in output_files
            },
        }
        manifest_path = final_dir / "tree-manifest.json"
        manifest_path.write_text(
            json.dumps(final_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        for path in output_files:
            store.upload(path, join_object(config.output_prefix, path.relative_to(final_dir).as_posix()))
        store.upload(manifest_path, join_object(config.output_prefix, "tree-manifest.json"))

    return FinalizeResult(
        output_prefix=config.output_prefix,
        leaf_count=partition_manifest.selected_leaf_count,
        partition_count=len(partition_manifest.partitions),
    )


def _write_upper_inputs(
    manifest: PartitionManifest,
    partition_dir: Path,
    upper_input: Path,
    store: ArtifactStore,
) -> None:
    records_path = upper_input / "records.tsv"
    index_path = upper_input / "embedding-index.tsv"
    fields = ["leaf_id", "record_id", "bin_uri", *TAXONOMY_RANKS]
    vectors: list[np.ndarray] = []
    with records_path.open("w", encoding="utf-8", newline="") as records_handle, index_path.open(
        "w", encoding="utf-8", newline=""
    ) as index_handle:
        record_writer = csv.DictWriter(records_handle, fieldnames=fields, delimiter="\t")
        index_writer = csv.DictWriter(
            index_handle, fieldnames=["record_id", "row_index"], delimiter="\t"
        )
        record_writer.writeheader()
        index_writer.writeheader()
        for row_index, partition in enumerate(manifest.partitions):
            leaf_id = f"partition_{partition.partition_id}"
            taxonomy = dict(partition.taxonomy_path)
            record_writer.writerow(
                {
                    "leaf_id": leaf_id,
                    "record_id": leaf_id,
                    "bin_uri": leaf_id,
                    **{rank: taxonomy.get(rank, "") for rank in TAXONOMY_RANKS},
                }
            )
            index_writer.writerow({"record_id": leaf_id, "row_index": row_index})
            vector = np.load(
                partition_dir / partition.partition_id / "root-representative.npy",
                allow_pickle=False,
            )
            if vector.shape != (manifest.vector_dimension,) or not np.isfinite(vector).all():
                raise FullScaleInputError(
                    f"invalid root representative for {partition.partition_id}"
                )
            vectors.append(np.asarray(vector, dtype=np.float32))
    np.save(upper_input / "embeddings.npy", np.vstack(vectors), allow_pickle=False)
    store.download(manifest.trust_policy_object, upper_input / "trust-policy.json")


def _graft_partition_trees(
    upper_newick: str,
    partitions: tuple[PartitionSpec, ...],
    partition_dir: Path,
) -> str:
    combined = upper_newick.strip()
    for partition in partitions:
        worker_tree = (
            partition_dir / partition.partition_id / "scaled-tree.nwk"
        ).read_text(encoding="utf-8").strip()
        if not worker_tree.endswith("root;"):
            raise FullScaleInputError(
                f"partition tree has an unexpected root: {partition.partition_id}"
            )
        worker_clade = worker_tree[: -len("root;")]
        leaf_id = f"partition_{partition.partition_id}"
        pattern = re.compile(rf"(?<![A-Za-z0-9_.-]){re.escape(leaf_id)}(?=:)")
        combined, replacements = pattern.subn(worker_clade, combined, count=1)
        if replacements != 1:
            raise FullScaleInputError(
                f"upper tree does not contain exactly one leaf for {partition.partition_id}"
            )
    return combined + "\n"


def _merge_tabular_outputs(
    upper_path: Path,
    partitions: tuple[PartitionSpec, ...],
    partition_dir: Path,
    filename: str,
    destination: Path,
) -> None:
    with destination.open("w", encoding="utf-8", newline="") as output_handle:
        wrote_header = False
        for path in [
            upper_path,
            *(
                partition_dir / partition.partition_id / filename
                for partition in partitions
            ),
        ]:
            with path.open(encoding="utf-8", newline="") as input_handle:
                header = input_handle.readline()
                if not wrote_header:
                    output_handle.write(header)
                    wrote_header = True
                for line in input_handle:
                    output_handle.write(line)


def _verify_declared_outputs(
    output_dir: Path,
    manifest: dict[str, object],
    partition_id: str,
) -> None:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise FullScaleInputError(f"worker outputs are missing for {partition_id}")
    for filename in (
        "scaled-tree.nwk",
        "root-representative.npy",
        "node-diagnostics.tsv",
        "excluded-records.tsv",
    ):
        expected = outputs.get(filename)
        if not isinstance(expected, str) or _sha256(output_dir / filename) != expected:
            raise FullScaleInputError(
                f"worker output checksum mismatch for {partition_id}/{filename}"
            )


def _validate_final_tree(path: Path, expected_leaf_count: int) -> None:
    try:
        import dendropy
    except ImportError as error:
        raise RuntimeError("tree finalization requires dendropy") from error
    tree = dendropy.Tree.get(path=str(path), schema="newick", preserve_underscores=True)
    leaf_labels = [leaf.taxon.label for leaf in tree.leaf_node_iter() if leaf.taxon]
    if len(leaf_labels) != expected_leaf_count:
        raise FullScaleInputError(
            f"final tree has {len(leaf_labels)} leaves; expected {expected_leaf_count}"
        )
    if len(leaf_labels) != len(set(leaf_labels)):
        raise FullScaleInputError("final tree contains duplicate leaf labels")
    for edge in tree.preorder_edge_iter():
        if edge.length is not None and (
            edge.length < 0 or not float(edge.length) < float("inf")
        ):
            raise FullScaleInputError("final tree contains an invalid branch length")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class _LocalDirectoryStore:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def download(self, object_name: str, destination: Path) -> None:
        destination.write_bytes((self._directory / object_name).read_bytes())

    def upload(self, source: Path, object_name: str) -> None:
        destination = self._directory / object_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
