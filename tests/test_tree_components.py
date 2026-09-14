from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from evospaice.tree.distance import CosineDistanceProvider
from evospaice.tree.inputs import InputValidationError, load_inputs
from evospaice.tree.lengths import NonNegativeLeastSquaresSolver
from evospaice.tree.models import InputPaths, TreeBuildConfig
from evospaice.tree.pipeline import TreeBuilder
from evospaice.tree.representatives import CentroidMedoidSelector
from evospaice.tree.topology import NeighborJoiningResolver


def test_cosine_distance_is_a_valid_local_block() -> None:
    vectors = np.asarray([[1.0, 0.0], [0.8, 0.2], [0.0, 1.0]], dtype=np.float32)

    distances = CosineDistanceProvider().pairwise(vectors)

    assert distances.shape == (3, 3)
    assert np.allclose(distances, distances.T)
    assert np.allclose(np.diag(distances), 0.0)
    assert np.all((0.0 <= distances) & (distances <= 2.0))


def test_representative_gives_each_child_one_vote() -> None:
    vectors = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    result = CentroidMedoidSelector(drift_limit=1.0).select(vectors)

    assert result.method == "centroid"
    assert np.allclose(result.vector, [2**-0.5, 2**-0.5])


def test_loader_rejects_duplicate_leaf_ids(tmp_path: Path) -> None:
    records = tmp_path / "records.tsv"
    with records.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["leaf_id", "record_id", "bin_uri", "kingdom"])
        writer.writerow(["same", "one", "same", "Animalia"])
        writer.writerow(["same", "two", "same", "Animalia"])
    embeddings = tmp_path / "embeddings.npy"
    np.save(embeddings, np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))

    with pytest.raises(InputValidationError, match="duplicate leaf_id"):
        load_inputs(InputPaths(records, embeddings, tmp_path / "output"))


def test_fanout_limit_prevents_square_distance_allocation(tmp_path: Path) -> None:
    records = tmp_path / "records.tsv"
    with records.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["leaf_id", "record_id", "bin_uri", "kingdom"])
        for index in range(4):
            writer.writerow([f"leaf-{index}", f"record-{index}", f"bin-{index}", "Animalia"])
    embeddings = tmp_path / "embeddings.npy"
    np.save(
        embeddings,
        np.asarray(
            [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]],
            dtype=np.float32,
        ),
    )

    class RecordingDistanceProvider(CosineDistanceProvider):
        def __init__(self) -> None:
            self.child_counts: list[int] = []

        def pairwise(self, vectors: np.ndarray) -> np.ndarray:
            self.child_counts.append(len(vectors))
            return super().pairwise(vectors)

    distance_provider = RecordingDistanceProvider()
    builder = TreeBuilder(
        distance_provider=distance_provider,
        topology_resolver=NeighborJoiningResolver(),
        branch_solver=NonNegativeLeastSquaresSolver(0.0),
        representative_selector=CentroidMedoidSelector(0.35),
    )

    builder.build(
        InputPaths(records, embeddings, tmp_path / "output"),
        TreeBuildConfig(max_nj_children=3),
    )

    assert 4 not in distance_provider.child_counts
