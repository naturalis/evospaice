import csv
import json
from itertools import product

import dendropy
import numpy as np
import pytest

from evospaice.validate.compare import prepare_trees, topology_metrics
from evospaice.validate.tree_metrics import (
    TreeIndex,
    errors,
    fitted_errors,
    kc_topology,
    neighbor_preservation,
    taxon_purity,
)
from evospaice.validate.whole_tree import _kc, run


def tree(text):
    return dendropy.Tree.get(
        data=text, schema="newick", preserve_underscores=True, rooting="force-rooted",
    )


def test_indexed_paths_and_mrcas_match_direct_queries():
    original = tree("(((A:1,B:2):3,C:4):5,(D:6,E:7):8):999;")
    index = TreeIndex(original)
    labels = list("ABCDE")
    pairs = np.array(list(product(range(5), repeat=2)))
    leaves = index.leaves(labels)
    ancestors = index.lca(leaves[pairs[:, 0]], leaves[pairs[:, 1]])
    observed = index.paths(leaves[pairs[:, 0]], leaves[pairs[:, 1]])
    direct = original.phylogenetic_distance_matrix()
    for row, (a, b) in enumerate(pairs):
        ancestor = original.mrca(taxon_labels=sorted({labels[a], labels[b]}))
        assert index.depth[ancestors[row]] == len(list(ancestor.ancestor_iter()))
        left = original.taxon_namespace.get_taxon(labels[a])
        right = original.taxon_namespace.get_taxon(labels[b])
        assert observed[row] == pytest.approx(direct.distance(left, right))
    assert index.descendant_tips[0] == 5
    assert index.distance[0] == 0


@pytest.mark.parametrize("text", ["((A,B:1):1,C:1);", "(A:-1,B:1,C:1);"])
def test_path_metrics_reject_unspecified_or_negative_lengths(text):
    with pytest.raises(ValueError, match="finite, nonnegative"):
        TreeIndex(tree(text))
    TreeIndex(tree(text), lengths=False)


def test_review_stress_is_squared_and_mape_reports_zero_denominators():
    result = errors(np.array([0., 2.]), np.array([1., 4.]))
    assert result["stress_squared"] == pytest.approx(5 / 4)
    assert result["normalized_stress"] == pytest.approx(np.sqrt(5 / 4))
    assert result["mae"] == pytest.approx(1.5)
    assert result["mape_percent"] == pytest.approx(100)
    assert result["mape_zero_targets_excluded"] == 1
    zero = errors(np.zeros(2), np.array([1., 2.]))
    assert zero["stress_squared"] is None
    assert zero["mape_percent"] is None
    assert zero["undefined"]["stress"]
    assert zero["pearson"] is None
    scaled = fitted_errors(np.array([2., 4.]), np.array([1., 2.]))
    assert scaled["scale"] == 2
    assert scaled["metrics"]["stress_squared"] == 0
    assert fitted_errors(np.ones(2), np.zeros(2))["status"] == "undefined"


def test_kc_known_rooted_quartets_and_sampling_expansion():
    first = np.array([1, 0, 0, 0, 0, 1])
    second = np.array([0, 1, 0, 0, 1, 0])
    result = kc_topology(first, second, 4)
    assert result["distance"] == 2
    assert result["normalized"] == pytest.approx(1 / np.sqrt(6))
    assert result["exact"]
    estimate = kc_topology(first[:3], second[:3], 4)
    assert not estimate["exact"]
    assert estimate["distance"] == 2
    assert kc_topology(first, first, 4)["distance"] == 0


def test_kc_common_outgroup_removes_arbitrary_root_differences():
    prepared, _ = prepare_trees({
        "centroid": tree("((A,B),(C,D));"),
        "reference": tree("(A,(B,(C,D)));"),
    }, mode="unrooted")
    pairs = np.array([(a, b) for a in range(4) for b in range(a + 1, 4)])
    result, _ = _kc(prepared, list("ABCD"), pairs)
    assert result["distance"] == 0
    assert result["rooting"]["outgroup_id"] == "A"


def test_rf_summary_avoids_per_clade_label_expansion(monkeypatch):
    prepared, _ = prepare_trees({
        "centroid": tree("((A,B),(C,D));"),
        "reference": tree("((A,C),(B,D));"),
    }, mode="unrooted")
    expected, _ = topology_metrics(prepared["centroid"], prepared["reference"])

    def forbidden(*args):
        pytest.fail("Whole-tree summary must not expand every split into a label list")

    monkeypatch.setattr("evospaice.validate.compare.split_id", forbidden)
    result, rows = topology_metrics(
        prepared["centroid"], prepared["reference"], include_clades=False,
    )
    assert result == expected
    assert rows == []


def test_alignment_uses_direct_taxon_mapping_instead_of_linear_label_scans(monkeypatch):
    originals = {"centroid": tree("((A,B),(C,D));"), "reference": tree("((A,C),(B,D));")}

    def forbidden(*args, **kwargs):
        pytest.fail("Aligned taxa should come from the explicit mapping")

    monkeypatch.setattr(dendropy.TaxonNamespace, "require_taxon", forbidden)
    monkeypatch.setattr(dendropy.TaxonNamespace, "get_taxa", forbidden)
    prepared, _ = prepare_trees(originals, mode="unrooted")
    assert prepared["centroid"].taxon_namespace is prepared["reference"].taxon_namespace
    assert topology_metrics(prepared["centroid"], prepared["reference"])[0]["rf"] == 2


def test_taxonomic_purity_and_singleton_reporting():
    indices = {
        "centroid": TreeIndex(tree("((A:1,B:1):1,(C:1,D:1):1);")),
        "reference": TreeIndex(tree("((A:1,C:1):1,(B:1,D:1):1);")),
    }
    taxonomy = np.array([
        ["Lepidoptera", "F", "G1", "G1 one"],
        ["Lepidoptera", "F", "G1", "G1 one"],
        ["Lepidoptera", "F", "G2", "G2 one"],
        ["Lepidoptera", "F", "G2", "G2 two"],
    ])
    summaries, rows = taxon_purity(indices, list("ABCD"), taxonomy)
    assert summaries["genus"]["centroid"]["macro_purity_nontrivial"] == 1
    assert summaries["genus"]["reference"]["macro_purity_nontrivial"] == .5
    assert summaries["species"]["reference"]["singleton_taxa"] == 2
    assert summaries["species"]["reference"]["nontrivial_taxa"] == 1
    assert summaries["species"]["reference"]["macro_purity_nontrivial"] == .5
    assert any(row["reference_mrca_tips"] == 4 for row in rows if row["rank"] == "genus")


def test_neighbors_search_all_candidates_and_exclude_self():
    indices = {
        "centroid": TreeIndex(tree("((A:1,B:1):1,(C:1,D:1):1);")),
        "reference": TreeIndex(tree("((A:1,C:1):1,(B:1,D:1):1);")),
    }
    vectors = np.array([[1., 0.], [.99, .1], [0., 1.], [.1, .99]])
    unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    result, rows = neighbor_preservation(indices, list("ABCD"), unit, k=1, anchors=4, seed=42)
    assert result["mean_precision_at_k"] == {"centroid": 1, "reference": 0}
    assert result["all_anchors_evaluated"]
    assert all(row["anchor_id"] not in row["embedding_neighbors"] for row in rows)
    subset, first = neighbor_preservation(indices, list("ABCD"), unit, k=1, anchors=2, seed=42)
    _, second = neighbor_preservation(indices, list("ABCD"), unit, k=1, anchors=2, seed=42)
    assert first == second
    assert subset["candidate_tips"] == 4
    assert subset["anchors"] == 2


def test_neighbor_ties_use_record_id_order():
    index = {"centroid": TreeIndex(tree("(A:1,B:1,C:1,D:1);"))}
    _, rows = neighbor_preservation(
        index, list("ABCD"), np.ones((4, 2)) / np.sqrt(2), k=2, anchors=4, seed=42,
    )
    assert rows[0]["embedding_neighbors"] == ["B", "C"]
    assert rows[0]["centroid_neighbors"] == ["B", "C"]


def test_whole_tree_report_uses_exact_intersection_and_preserves_inputs(tmp_path):
    inferred, reference, bundle = [
        tmp_path / name for name in ("centroid.nwk", "ref.nwk", "data.npz")
    ]
    inferred.write_text("(((A:1,B:1):1,(C:1,D:1):1):2,E:3);")
    reference.write_text("(((A:2,B:2):2,(C:2,D:2):2):4,F:6);")
    before = inferred.read_bytes(), reference.read_bytes()
    np.savez(
        bundle, ids=np.array(list("ABCD")),
        embeddings=np.array([[1., 0.], [.99, .1], [0., 1.], [.1, .99]]),
        order=np.array(["Lepidoptera"] * 4), family=np.array(["F"] * 4),
        genus=np.array(["G1", "G1", "G2", "G2"]),
        species=np.array(["G1 one", "G1 one", "G2 one", "G2 one"]),
    )
    output = tmp_path / "report"
    result = run(inferred, reference, bundle, output, pair_limit=100, anchors=4, k=1)
    assert result["coverage"]["shared_tips"] == 4
    assert result["coverage"]["centroid"]["excluded_tips"] == 1
    assert result["coverage"]["reference"]["excluded_tips"] == 1
    assert result["topology"]["rf"]["rf"] == 0
    assert result["topology"]["kendall_colijn"]["exact"]
    assert result["topology"]["kendall_colijn"]["distance"] == 0
    assert result["sampling"]["sampled_pairs"] == 6
    assert result["reference_path_comparison"]["scale_aligned"]["scale"] == 2
    assert result["reference_path_comparison"]["scale_aligned"]["metrics"]["mae"] == 0
    assert json.loads((output / "report.json").read_text())["not_computed"]["bootstrap_support"]
    assert "/* VALIDATION_DATA */ null" not in (output / "index.html").read_text()
    with (output / "taxa.tsv").open() as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 10
    assert sum(row["retained"] == "False" for row in rows) == 2
    assert before == (inferred.read_bytes(), reference.read_bytes())
    with pytest.raises(FileExistsError):
        run(inferred, reference, bundle, output, k=1)
