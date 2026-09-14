from pathlib import Path

import dendropy
import pytest

from evospaice.diversity.evaluate import evaluate, load_samples
from evospaice.diversity.metrics import faith_pd, unweighted_unifrac, weighted_unifrac

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def tree() -> dendropy.Tree:
    return dendropy.Tree.get(
        path=str(DATA_DIR / "diversity_tree.nwk"),
        schema="newick",
        rooting="force-rooted",
    )


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ({"A": 1, "B": 1}, 0.10),
        ({"C": 1, "D": 1}, 0.47),
        ({"A": 1, "D": 1}, 0.42),
    ],
)
def test_faith_pd_known_answers(
    tree: dendropy.Tree,
    sample: dict[str, int],
    expected: float,
) -> None:
    assert faith_pd(tree, sample) == pytest.approx(expected)


def test_unweighted_unifrac_is_zero_for_identical_samples(tree: dendropy.Tree) -> None:
    assert unweighted_unifrac(tree, {"A": 1, "B": 1}, {"A": 5, "B": 2}) == 0


def test_unweighted_unifrac_is_one_for_disjoint_clades(tree: dendropy.Tree) -> None:
    assert unweighted_unifrac(tree, {"A": 1, "B": 1}, {"C": 1, "D": 1}) == 1


def test_weighted_unifrac_uses_relative_abundance(tree: dendropy.Tree) -> None:
    distance = weighted_unifrac(tree, {"A": 9, "B": 1}, {"A": 1, "B": 9})
    assert distance == pytest.approx(4 / 15)


def test_unknown_taxon_is_rejected(tree: dendropy.Tree) -> None:
    with pytest.raises(ValueError, match="absent from the tree: missing"):
        faith_pd(tree, {"missing": 1})


def test_negative_abundance_is_rejected(tree: dendropy.Tree) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        faith_pd(tree, {"A": -1})


def test_fixture_evaluates_all_samples(tree: dendropy.Tree) -> None:
    samples = load_samples(DATA_DIR / "diversity_samples.tsv")
    alpha, beta = evaluate(tree, samples)

    assert len(alpha) == 5
    assert len(beta) == 10
