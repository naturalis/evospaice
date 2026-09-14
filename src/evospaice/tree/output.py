"""Validation and atomic publication of tree-building artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

import numpy as np
from numpy.typing import NDArray

from .backbone import TreeGraph
from .models import BuildResult, InputPaths, NodeDiagnostic, TreeBuildConfig, TreeRecord
from .policy import TrustPolicy


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _newick_label(label: str) -> str:
    if not label:
        return ""
    if any(character in " \t\n\r()[]{},:;'\"" for character in label):
        return f"'{label.replace(chr(39), chr(39) * 2)}'"
    return label


def _newick(graph: TreeGraph, node_id: str) -> str:
    node = graph.nodes[node_id]
    children = ""
    if node.child_ids:
        children = f"({','.join(_newick(graph, child_id) for child_id in node.child_ids)})"
    label = _newick_label(node.label)
    length = "" if node.parent_id is None else f":{float(node.branch_length or 0.0):.12g}"
    return f"{children}{label}{length}"


def validate_tree(graph: TreeGraph, records: tuple[TreeRecord, ...]) -> None:
    expected_leaves = {record.leaf_id for record in records}
    observed_leaves: list[str] = []
    visited: set[str] = set()
    stack = [graph.root_id]
    while stack:
        node_id = stack.pop()
        if node_id in visited:
            raise ValueError(f"cycle or duplicate tree attachment at {node_id}")
        visited.add(node_id)
        node = graph.nodes[node_id]
        if node.parent_id is not None:
            length = node.branch_length
            if length is None or length < 0 or not float(length) < float("inf"):
                raise ValueError(f"invalid branch length at {node_id}: {length}")
        if node.is_leaf:
            observed_leaves.append(node.leaf_id or "")
        stack.extend(node.child_ids)
    if len(observed_leaves) != len(set(observed_leaves)):
        raise ValueError("tree contains duplicate leaves")
    if set(observed_leaves) != expected_leaves:
        raise ValueError("tree leaves do not match validated input leaves")


class ArtifactWriter:
    """Publish the portable scientific record after validation succeeds."""

    def write(
        self,
        graph: TreeGraph,
        records: tuple[TreeRecord, ...],
        diagnostics: Iterable[NodeDiagnostic],
        paths: InputPaths,
        config: TreeBuildConfig,
        policy: TrustPolicy,
        root_representative: NDArray[np.floating],
    ) -> BuildResult:
        validate_tree(graph, records)
        paths.output_dir.mkdir(parents=True, exist_ok=True)
        tree_path = paths.output_dir / "scaled-tree.nwk"
        diagnostics_path = paths.output_dir / "node-diagnostics.tsv"
        exclusions_path = paths.output_dir / "excluded-records.tsv"
        representative_path = paths.output_dir / "root-representative.npy"
        manifest_path = paths.output_dir / "tree-manifest.json"
        checkpoint_path = paths.output_dir / "checkpoints" / "complete.json"

        diagnostic_rows = list(diagnostics)
        _atomic_text(tree_path, f"{_newick(graph, graph.root_id)};\n")
        self._write_diagnostics(diagnostics_path, diagnostic_rows)
        _atomic_text(exclusions_path, "leaf_id\trecord_id\treason\n")
        self._write_representative(representative_path, root_representative)
        _atomic_text(
            checkpoint_path,
            json.dumps(
                {"status": "complete", "processed_nodes": len(diagnostic_rows)},
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )

        input_paths = [paths.records, paths.embeddings]
        if paths.embedding_index is not None:
            input_paths.append(paths.embedding_index)
        if paths.trust_policy is not None:
            input_paths.append(paths.trust_policy)
        manifest = {
            "schema_version": 1,
            "status": "complete",
            "policy_version": policy.version,
            "config": asdict(config),
            "counts": {
                "leaves": len(records),
                "nodes": len(graph.nodes),
                "processed_internal_nodes": len(diagnostic_rows),
            },
            "distance_scope": {
                "global_matrix_created": False,
                "largest_local_child_count": max(
                    (row.child_count for row in diagnostic_rows), default=0
                ),
                "largest_local_matrix_elements": max(
                    (row.distance_matrix_size for row in diagnostic_rows), default=0
                ),
            },
            "inputs": {path.name: _sha256(path) for path in input_paths},
            "outputs": {
                tree_path.name: _sha256(tree_path),
                diagnostics_path.name: _sha256(diagnostics_path),
                exclusions_path.name: _sha256(exclusions_path),
                representative_path.name: _sha256(representative_path),
            },
        }
        _atomic_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return BuildResult(
            tree_path=tree_path,
            diagnostics_path=diagnostics_path,
            exclusions_path=exclusions_path,
            manifest_path=manifest_path,
            leaf_count=len(records),
            node_count=len(graph.nodes),
        )

    @staticmethod
    def _write_representative(path: Path, vector: NDArray[np.floating]) -> None:
        values = np.asarray(vector, dtype=np.float32)
        if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
            raise ValueError("root representative must be a finite non-empty vector")
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        os.close(descriptor)
        try:
            with Path(temporary_name).open("wb") as handle:
                np.save(handle, values, allow_pickle=False)
            os.replace(temporary_name, path)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _write_diagnostics(path: Path, rows: list[NodeDiagnostic]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=list(NodeDiagnostic.__dataclass_fields__),
                    delimiter="\t",
                )
                writer.writeheader()
                writer.writerows(asdict(row) for row in rows)
            os.replace(temporary_name, path)
        except BaseException:
            Path(temporary_name).unlink(missing_ok=True)
            raise
