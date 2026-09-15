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


def test_fractional_abundances(tree: dendropy.Tree) -> None:
    assert faith_pd(tree, {"A": 0.01, "B": 0.02}) == pytest.approx(0.10)
    assert weighted_unifrac(tree, {"A": 0.09, "B": 0.01}, {"A": 0.01, "B": 0.09}) == (
        pytest.approx(4 / 15)
    )


def test_empty_sample_contract(tree: dendropy.Tree) -> None:
    assert faith_pd(tree, {}) == 0
    assert unweighted_unifrac(tree, {}, {"A": 1}) == 1
    with pytest.raises(ValueError):
        unweighted_unifrac(tree, {}, {})
    with pytest.raises(ValueError):
        weighted_unifrac(tree, {}, {"A": 1})
    assert evaluate(tree, {"empty": {}}) == ([{"sample": "empty", "faith_pd": 0}], [])


def test_root_stem_excluded_without_mutation(tree: dendropy.Tree) -> None:
    tree.seed_node.edge_length = 100
    original = tree.as_string(schema="newick")
    assert faith_pd(tree, {"A": 1, "B": 1}) == pytest.approx(0.10)
    assert tree.as_string(schema="newick") == original


@pytest.mark.parametrize("abundance", [-1, float("nan"), float("inf")])
def test_invalid_abundances(tree: dendropy.Tree, abundance: float) -> None:
    with pytest.raises(ValueError):
        faith_pd(tree, {"A": abundance})


def test_zero_length_tree() -> None:
    tree = dendropy.Tree.get(data="(A:0,B:0,C:0);", schema="newick", rooting="force-rooted")
    assert faith_pd(tree, {"A": 1}) == 0
    with pytest.raises(ValueError):
        unweighted_unifrac(tree, {"A": 1}, {"B": 1})
    with pytest.raises(ValueError):
        weighted_unifrac(tree, {"A": 1}, {"B": 1})


def test_batch_fractional_matches_scalar(tree: dendropy.Tree) -> None:
    samples = {"z": {"A": 0.09, "B": 0.01}, "a": {"A": 0.01, "B": 0.09}}
    alpha, beta = evaluate(tree, samples)
    assert [row["sample"] for row in alpha] == ["a", "z"]
    assert alpha[0]["faith_pd"] == pytest.approx(0.10)
    assert beta[0]["weighted_unifrac"] == pytest.approx(4 / 15)


def test_memory_budget(tree: dendropy.Tree) -> None:
    with pytest.raises(ValueError, match="budget"):
        evaluate(tree, {"a": {"A": 1}}, memory_mb=0.00001)


def test_native_matches_skbio(tree: dendropy.Tree) -> None:
    pytest.importorskip("unifrac")
    samples = {"z": {"A": 0.09, "B": 0.01}, "a": {"A": 0.01, "B": 0.09}}
    expected_alpha, expected_beta = evaluate(tree, samples)
    alpha, beta = evaluate(tree, samples, backend="unifrac")
    assert alpha == expected_alpha
    for metric in ("weighted_unifrac", "unweighted_unifrac"):
        assert beta[0][metric] == pytest.approx(expected_beta[0][metric], rel=1e-8, abs=1e-10)
    assert weighted_unifrac(tree, samples["z"], samples["a"], backend="unifrac") == (
        pytest.approx(4 / 15)
    )


@pytest.mark.parametrize("body", [
    "sample\ttaxon\tabundance\ns\tA\n",
    "sample\ttaxon\tabundance\ns\tA\tNaN\n",
    "sample\ttaxon\tabundance\tabundance\ns\tA\t1\t2\n",
])
def test_malformed_sample_tables(tmp_path, body):
    path = tmp_path / "samples.tsv"
    path.write_text(body)
    with pytest.raises(ValueError):
        load_samples(path)


def test_polytomy_and_exact_labels():
    tree = dendropy.Tree.get(
        data="('BOLD:A_a':1,'name with space':2,'A':3,'a':4);", schema="newick",
        rooting="force-rooted", preserve_underscores=True,
        taxon_namespace=dendropy.TaxonNamespace(is_case_sensitive=True),
        case_sensitive_taxon_labels=True,
    )
    assert faith_pd(tree, {"BOLD:A_a": .2, "a": .3}) == 5
    assert weighted_unifrac(tree, {"A": .1}, {"a": .1}) == 1


def test_explicitly_unrooted_rejected(tree):
    tree.is_rooted = False
    with pytest.raises(ValueError, match="rooted"):
        faith_pd(tree, {"A": 1})


def test_cli_and_module_outputs(tmp_path):
    import csv
    import json

    from evospaice.cli import main as cli_main
    from evospaice.diversity.evaluate import main as module_main

    args = ["--tree", str(DATA_DIR / "diversity_tree.nwk"),
            "--samples", str(DATA_DIR / "diversity_samples.tsv")]
    for name, function, prefix in [("cli", cli_main, ["diversity"]), ("module", module_main, [])]:
        output = tmp_path / name
        assert function(prefix + args + ["--output-dir", str(output)]) == 0
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["backend"] == "skbio"
        assert manifest["weighted_normalized"]
        with (output / "alpha_diversity.csv").open() as handle:
            assert len(list(csv.DictReader(handle))) == 5
        with (output / "beta_diversity.csv").open() as handle:
            assert len(list(csv.DictReader(handle))) == 10
    assert (tmp_path / "cli" / "alpha_diversity.csv").read_text() == (
        tmp_path / "module" / "alpha_diversity.csv"
    ).read_text()
