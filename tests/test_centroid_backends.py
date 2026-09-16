from collections import Counter
from itertools import combinations

import numpy as np
import pytest
from Bio.Phylo.BaseTree import Clade, Tree
from scipy.spatial.distance import pdist, squareform

from evospaice.tree.centroid import NJ_BACKENDS, graft_nj, run
from evospaice.validate.compare import leaf_labels, load_tree


def connector(distances: np.ndarray, backend: str) -> tuple[Tree, Counter]:
    count = len(squareform(distances))
    diagnostics = Counter()
    root = graft_nj(
        "parent", [Clade(name=f"leaf_{i}") for i in range(count)],
        distances, diagnostics, nj_backend=backend,
    )
    return Tree(root=root), diagnostics


@pytest.mark.parametrize("seed", range(5))
def test_compiled_connector_matches_baseline_paths_and_midpoint(seed: int) -> None:
    vectors = np.random.default_rng(seed).normal(size=(24, 12)) + 2
    distances = pdist(vectors, metric="cosine")
    original, _ = connector(distances, "biopython")
    native, diagnostics = connector(distances, "skbio")
    labels = {leaf.name for leaf in native.get_terminals()}
    assert labels == {leaf.name for leaf in original.get_terminals()}
    diameter = 0
    for first, second in combinations(sorted(labels), 2):
        observed = native.distance(first, second)
        assert observed == pytest.approx(original.distance(first, second), abs=1e-10)
        diameter = max(diameter, observed)
    assert max(native.depths().values()) == pytest.approx(diameter / 2, abs=1e-10)
    assert diagnostics["skbio_nj_merges"] == 1


@pytest.mark.parametrize("backend", NJ_BACKENDS)
@pytest.mark.parametrize("count", [1, 2, 3, 8])
def test_zero_distances_and_small_groups_preserve_every_leaf(backend: str, count: int) -> None:
    diagnostics = Counter()
    root = graft_nj(
        "zero", [Clade(name=f"leaf_{i}") for i in range(count)],
        np.zeros(count * (count - 1) // 2), diagnostics, nj_backend=backend,
    )
    assert len(root.get_terminals()) == count
    assert all((node.branch_length or 0) == 0 for node in root.find_clades())


@pytest.mark.parametrize("backend", NJ_BACKENDS)
def test_negative_edges_are_counted_before_clamping(backend: str) -> None:
    tree, diagnostics = connector(np.array([1., 1., 3.]), backend)
    assert diagnostics["negative_edges_clamped"] == 1
    assert all((node.branch_length or 0) >= 0 for node in tree.find_clades())
    assert tree.distance("leaf_1", "leaf_2") == pytest.approx(3)
    assert tree.distance("leaf_0", "leaf_1") == pytest.approx(1.5)


@pytest.mark.parametrize("backend", NJ_BACKENDS)
def test_complete_subtrees_are_grafted_without_changing_internal_paths(backend: str) -> None:
    child = Clade(name="species:A", clades=[
        Clade(name="a_1", branch_length=.2), Clade(name="a_2", branch_length=.3),
    ])
    root = graft_nj(
        "parent", [child, Clade(name="b"), Clade(name="c")],
        np.array([.3, .5, .4]), Counter(), nj_backend=backend,
    )
    tree = Tree(root=root)
    assert tree.distance("a_1", "a_2") == pytest.approx(.5)
    assert {leaf.name for leaf in tree.get_terminals()} == {"a_1", "a_2", "b", "c"}
    assert child in list(tree.find_clades())


def test_compiled_run_records_backend_and_preserves_source_ids(tmp_path) -> None:
    path = tmp_path / "input.npz"
    ids = np.array([f"process_{i}" for i in range(6)])
    np.savez(
        path, ids=ids, embeddings=np.random.default_rng(42).uniform(size=(6, 8)),
        order=np.array(["Lepidoptera"] * 6), family=np.array(["Geometridae"] * 6),
        genus=np.array(["A"] * 6), species=np.array([f"A species_{i}" for i in range(6)]),
    )
    output = tmp_path / "result"
    report = run(path, output, families=None, nj_backend="skbio")
    assert report["algorithm"]["nj_backend"] == "skbio"
    assert report["algorithm"]["nj_backend_version"]
    assert report["diagnostics"]["skbio_nj_merges"] == 1
    assert report["coverage"]["retained"] == 6
    assert report["runtime"]["seconds"] > 0
    assert leaf_labels(load_tree(output / "centroid.nwk")) == set(ids)


def test_unknown_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown NJ backend"):
        graft_nj("parent", [Clade(name="a")], np.array([]), Counter(), nj_backend="invalid")
