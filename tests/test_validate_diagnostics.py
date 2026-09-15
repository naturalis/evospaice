import itertools

import dendropy
import numpy as np
import pytest

from evospaice.validate.compare import PathDistances, prepare_trees, sample_pairs
from evospaice.validate.diagnostics import (
    embedding_diagnostics,
    load_distances,
    load_vectors,
    pair_stratum,
    replicate_support,
)


@pytest.fixture
def aligned():
    tree = dendropy.Tree.get(data="((A:1,B:2):3,(C:4,D:5):6);", schema="newick")
    return prepare_trees({"inferred": tree, "reference": tree}, mode="rooted")[0]


def test_additive_distances(aligned):
    paths = PathDistances(aligned["inferred"])
    pairs = sample_pairs(list("ABCD"))
    distances = {pair: {"embedding_distance": paths.distance(*pair)} for pair in pairs}
    result, rows, summaries = embedding_diagnostics(
        **aligned, pairs=pairs, distances=distances, same_embedding_units=True
    )
    assert result["reconstruction_fit"]["rmse"] == 0
    assert result["quartets"]["mean_gap"] == 0
    assert result["unknown_taxonomy_pairs"] == 6
    assert len(rows) == 6
    assert summaries[0]["count"] == 6
    assert result["reference_depth_bin_boundaries"]
    assert all("reference_mrca_depth" in row for row in rows)
    distances[("A", "C")]["embedding_distance"] += 2
    result, _, _ = embedding_diagnostics(**aligned, pairs=pairs, distances=distances)
    assert result["quartets"]["mean_gap"] == 2


def test_vector_and_table_equivalence(aligned, tmp_path):
    path = tmp_path / "vectors.npz"
    np.savez(path, taxa=np.array(list("ABCD")), vectors=np.eye(4))
    vectors, changed = load_vectors(path, set("ABCD"))
    assert not changed
    pairs = sample_pairs(list("ABCD"))
    distances = {pair: {"embedding_distance": 1.0} for pair in pairs}
    vector_result = embedding_diagnostics(**aligned, pairs=pairs, vectors=vectors)
    table_result = embedding_diagnostics(**aligned, pairs=pairs, distances=distances)
    assert vector_result == table_result


def test_replicate_support(aligned, tmp_path):
    path = tmp_path / "replicates.nwk"
    path.write_text("((A,B),(C,D));\n((B,A),(D,C));\n((A,C),(B,D));\n")
    result = replicate_support(path, aligned["inferred"], kind="bootstrap",
                               method="aligned sites resampled", mode="rooted")
    assert result["replicates"] == 3
    assert all(row["support"] == pytest.approx(2 / 3) for row in result["clades"])
    path.write_text("((A,B),C);")
    with pytest.raises(ValueError, match="all benchmark taxa"):
        replicate_support(path, aligned["inferred"], kind="other", method="test", mode="rooted")


def test_unknown_and_conflicting_lineages():
    assert pair_stratum("A", "B", {}) == "unknown"
    taxonomy = {"A": ("animal", None, None, None, "family1", "same", "same"),
                "B": ("animal", None, None, None, "family2", "same", "same")}
    assert pair_stratum("A", "B", taxonomy) == "kingdom"


def test_distance_table_duplicate_reversed(tmp_path):
    path = tmp_path / "distances.tsv"
    path.write_text("taxon_a\ttaxon_b\tembedding_distance\nA\tB\t1\nB\tA\t1\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_distances(path, set("AB"))


def test_tip_compression(aligned):
    taxonomy = {label: ("animal", "arthropod", "insect", "order", "family", "genus",
                        "species1" if label in "AB" else "species2") for label in "ABCD"}
    distances = {pair: {"embedding_distance": 0.0 if pair in [("A", "B"), ("C", "D")] else 1.0,
                        "kmer_distance": .5} for pair in itertools.combinations("ABCD", 2)}
    result, _, summaries = embedding_diagnostics(
        **aligned, pairs=sample_pairs(list("ABCD")), distances=distances, taxonomy=taxonomy,
        near_zero=.01,
    )
    assert result["within_species_pairs"] == 2
    compressed = next(row for row in summaries if row["stratum"] == "species"
                      and row["method"] == "embedding_distance")
    assert compressed["near_zero_fraction"] == 1


def test_diversity_sensitivity_identity_and_empty(aligned):
    from evospaice.validate.evaluate import diversity_sensitivity

    samples = {"first": {"A": .1}, "second": {"D": .2}, "empty": {"absent": 1}}
    with pytest.raises(ValueError, match="outside"):
        diversity_sensitivity(**aligned, samples=samples)
    report, alpha, beta = diversity_sensitivity(
        **aligned, samples=samples, length_mode="total-length", taxa_policy="intersection"
    )
    assert report["pd"]["rmse"] == 0
    assert alpha[0]["retained_abundance_fraction"] == 0
    assert any(row["weighted_unifrac_delta"] is None for row in beta)
    assert all(row["unweighted_unifrac_delta"] == 0 for row in beta)