from io import StringIO

import numpy as np
import pytest
from Bio import Phylo

from evospaice.tree.centroid import Dataset, build_tree
from evospaice.tree.compare_representations import (
    METHODS,
    build_genus,
    gaussian,
    gaussian_w2,
    gsc_weights,
    spherical_mean,
)


def test_low_rank_wasserstein_matches_one_dimensional_formula() -> None:
    first = (np.array([1.]), np.array([[2.]]))
    second = (np.array([4.]), np.array([[5.]]))
    assert gaussian_w2(first, second) == pytest.approx(np.sqrt(3**2 + 3**2))
    point_a = gaussian(np.array([[1., 2.]]))
    point_b = gaussian(np.array([[4., 6.]]))
    assert gaussian_w2(point_a, point_b) == pytest.approx(5)
    assert gaussian_w2(first, first) == pytest.approx(0)


def test_gaussian_factor_is_the_unbiased_sample_covariance() -> None:
    vectors = np.array([[1., 2.], [2., 4.], [5., 3.]])
    mean, factor = gaussian(vectors)
    np.testing.assert_allclose(mean, vectors.mean(axis=0))
    np.testing.assert_allclose(factor @ factor.T, np.cov(vectors, rowvar=False))


def test_gsc_shared_edges_are_distributed_among_descendant_leaves() -> None:
    tree = Phylo.read(StringIO("(a:1,(b:1,c:3):2);"), "newick")
    weights, fallback = gsc_weights(tree.root, ["a", "b", "c"])
    np.testing.assert_allclose(weights, np.array([1, 2, 4]) / 7)
    assert not fallback
    zero = Phylo.read(StringIO("(a:0,b:0);"), "newick")
    weights, fallback = gsc_weights(zero.root, ["a", "b"])
    np.testing.assert_allclose(weights, [.5, .5])
    assert fallback


def test_intrinsic_spherical_mean_and_antipodal_error() -> None:
    point, _ = spherical_mean(np.array([[3., 0.], [0., 5.]]))
    np.testing.assert_allclose(point, np.array([1., 1.]) / np.sqrt(2), atol=1e-10)
    with pytest.raises(ValueError, match="antipodal"):
        spherical_mean(np.array([[1., 0.], [-1., 0.]]))


@pytest.fixture
def small_genus() -> Dataset:
    rng = np.random.default_rng(7)
    return Dataset(
        np.array([f"record_{i}" for i in range(9)]),
        rng.normal(scale=.1, size=(9, 4)) + np.array([1., 2., 3., 4.]),
        np.array([
            ["Lepidoptera", "Papilionidae", "Papilio", f"Papilio species_{i // 3}"]
            for i in range(9)
        ]),
        {"retained": 9},
    )


@pytest.mark.parametrize("method", METHODS)
def test_methods_preserve_the_identical_leaf_set_and_nonnegative_lengths(
    small_genus: Dataset, method: str
) -> None:
    tree, _ = build_genus(small_genus, method)
    assert {leaf.name for leaf in tree.get_terminals()} == set(small_genus.ids)
    assert all(np.isfinite(node.branch_length or 0) and (node.branch_length or 0) >= 0
               for node in tree.find_clades())


def test_centroid_variant_matches_the_existing_baseline(small_genus: Dataset) -> None:
    original, _ = build_tree(small_genus)
    compared, _ = build_genus(small_genus, "centroid")
    for first in small_genus.ids:
        for second in small_genus.ids:
            assert compared.distance(first, second) == pytest.approx(
                original.distance(first, second), abs=1e-12
            )
