import json
import subprocess
import sys
from collections import Counter
from io import StringIO
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
from Bio import Phylo
from Bio.Phylo.BaseTree import Tree
from scipy.spatial.distance import pdist, squareform

from evospaice import cli
from evospaice.tree import centroid
from evospaice.tree.centroid import NJ_BACKENDS, RANKS, Dataset, build_tree, run
from evospaice.tree.compare_representations import build_genus
from evospaice.tree.representations import METHODS, cosine_medoid, gaussian, gaussian_w2
from evospaice.validate.compare import leaf_labels, load_tree


@pytest.fixture
def hierarchy() -> Dataset:
    rows = []
    for order in range(2):
        for family in range(2 + order):
            for genus in range(2):
                for species in range(1 + genus):
                    # Repeated labels across ancestors must not merge different taxa.
                    rows.extend([[f"O{order}", f"F{family}", f"G{genus}", f"S{species}"]]
                                * (1 + (order + family + genus + species) % 4))
    rng = np.random.default_rng(13)
    angles = rng.uniform(.05, 1.35, len(rows))
    vectors = np.column_stack([np.cos(angles), np.sin(angles)])
    vectors *= rng.uniform(.4, 7, (len(rows), 1))
    return Dataset(np.array([f"id_{i}" for i in range(len(rows))]), vectors,
                   np.array(rows), {"retained": len(rows)})


def save_bundle(path: Path, data: Dataset) -> Path:
    np.savez(path, ids=data.ids, embeddings=data.embeddings,
             **{rank: data.taxonomy[:, depth] for depth, rank in enumerate(RANKS)})
    return path


def newick(tree: Tree) -> str:
    stream = StringIO()
    Phylo.write(tree, stream, "newick", format_branch_length="%1.12g")
    return stream.getvalue()


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("backend", NJ_BACKENDS)
def test_full_hierarchy_is_monophyletic_complete_nonnegative_and_deterministic(
    hierarchy, method, backend,
) -> None:
    tree, diagnostics = build_tree(hierarchy, method=method, nj_backend=backend)
    assert len(tree.get_terminals()) == len(hierarchy.ids)
    assert {leaf.name for leaf in tree.get_terminals()} == set(hierarchy.ids)
    assert all(np.isfinite(node.branch_length or 0) and (node.branch_length or 0) >= 0
               for node in tree.find_clades())
    for depth, rank in enumerate(RANKS):
        groups = {tuple(row[:depth + 1]) for row in hierarchy.taxonomy}
        for group in groups:
            ids = {str(hierarchy.ids[i]) for i, row in enumerate(hierarchy.taxonomy)
                   if tuple(row[:depth + 1]) == group}
            assert any(node.name == f"{rank}:{group[-1]}"
                       and {leaf.name for leaf in node.get_terminals()} == ids
                       for node in tree.find_clades())
    again, repeated = build_tree(hierarchy, method=method, nj_backend=backend)
    assert newick(tree) == newick(again)
    assert diagnostics == repeated
    assert diagnostics["maximum_fanout"] <= 4


def independent_gsc(root, ids):
    weights = {}
    tree = Tree(root=root)
    for leaf in root.get_terminals():
        weights[leaf.name] = sum(
            (node.branch_length or 0) / len(node.get_terminals())
            for node in tree.get_path(leaf)
        )
    values = np.array([weights[i] for i in ids])
    return values / values.sum() if values.sum() else np.ones(len(ids)) / len(ids)


@pytest.mark.parametrize("method", METHODS)
def test_actual_representatives_at_every_rank_use_all_descendants(
    hierarchy, method, monkeypatch,
) -> None:
    visited = Counter()
    lookup = dict(zip(map(str, hierarchy.ids), hierarchy.embeddings, strict=True))
    original_combine = centroid.combine
    original_represent = centroid.represent

    def check(vectors, ids, root, result):
        visited[root.name.split(":")[0]] += 1
        if method == "centroid":
            np.testing.assert_allclose(result, vectors.mean(axis=0), atol=1e-13)
        elif method == "medoid":
            totals = squareform(pdist(vectors, metric="cosine")).sum(axis=1)
            selected = np.flatnonzero(np.all(vectors == result, axis=1))
            assert len(selected) >= 1
            assert totals[selected[0]] == pytest.approx(totals.min(), abs=1e-12)
        elif method == "weighted":
            np.testing.assert_allclose(result, independent_gsc(root, ids) @ vectors, atol=1e-13)
        elif method == "wasserstein":
            mean, factor = result
            expected = np.cov(vectors, rowvar=False) if len(vectors) > 1 else np.zeros((2, 2))
            np.testing.assert_allclose(mean, vectors.mean(axis=0), atol=1e-13)
            np.testing.assert_allclose(factor @ factor.T, expected, atol=1e-12)
            assert factor.shape[1] <= vectors.shape[1]
        else:
            angle = np.arctan2(vectors[:, 1], vectors[:, 0]).mean()
            np.testing.assert_allclose(result, [np.cos(angle), np.sin(angle)], atol=1e-8)

    def traced_combine(*args, **kwargs):
        result = original_combine(*args, **kwargs)
        ids = [leaf.name for leaf in result.root.get_terminals()]
        check(np.array([lookup[i] for i in ids]), ids, result.root, result.centroid)
        return result

    def traced_represent(vectors, ids, root, selected_method, diagnostics):
        result = original_represent(vectors, ids, root, selected_method, diagnostics)
        check(vectors, ids, root, result)
        return result

    monkeypatch.setattr(centroid, "combine", traced_combine)
    monkeypatch.setattr(centroid, "represent", traced_represent)
    build_tree(hierarchy, method=method)
    assert all(visited[rank] > 0 for rank in RANKS)
    assert sum(visited.values()) == 1 + sum(
        len({tuple(row[:depth + 1]) for row in hierarchy.taxonomy})
        for depth in range(len(RANKS))
    )


@pytest.mark.parametrize("method", METHODS)
def test_parent_nj_uses_selected_representatives_not_centroid_fallback(
    hierarchy, method, monkeypatch,
) -> None:
    saved = {}
    original_represent = centroid.represent
    original_graft = centroid.graft_nj
    checked = Counter()

    def traced_represent(vectors, ids, root, selected_method, diagnostics):
        result = original_represent(vectors, ids, root, selected_method, diagnostics)
        saved[root] = result
        return result

    def traced_graft(name, roots, distances, *args, **kwargs):
        representatives = []
        for root in roots:
            if root.is_terminal():
                vector = hierarchy.embeddings[np.flatnonzero(hierarchy.ids == root.name)[0]]
                representatives.append(gaussian(vector[None, :]) if method == "wasserstein"
                                       else vector)
            elif method == "centroid":
                indices = [np.flatnonzero(hierarchy.ids == leaf.name)[0]
                           for leaf in root.get_terminals()]
                representatives.append(hierarchy.embeddings[indices].mean(axis=0))
            else:
                representatives.append(saved[root])
        expected = (
            np.array([gaussian_w2(a, b) for a, b in combinations(representatives, 2)])
            if method == "wasserstein"
            else np.clip(pdist(representatives, metric="cosine"), 0, 2)
        )
        np.testing.assert_allclose(distances, expected, atol=1e-12)
        checked[name.split(":")[0]] += 1
        return original_graft(name, roots, distances, *args, **kwargs)

    monkeypatch.setattr(centroid, "represent", traced_represent)
    monkeypatch.setattr(centroid, "graft_nj", traced_graft)
    build_tree(hierarchy, method=method)
    assert all(checked[rank] for rank in RANKS)


def test_cosine_medoid_can_be_a_record_that_is_not_any_child_medoid() -> None:
    angles = np.array([0., .2, .4, .6, .9, 1.2, 1.25])
    vectors = np.column_stack([np.cos(angles), np.sin(angles)])
    selected = cosine_medoid(vectors)
    np.testing.assert_array_equal(selected, vectors[3])
    assert not np.array_equal(selected, cosine_medoid(vectors[:3]))
    assert not np.array_equal(selected, cosine_medoid(vectors[3:]))
    tied = np.array([[2., 0.], [0., 3.]])
    np.testing.assert_array_equal(cosine_medoid(tied), tied[0])


def test_gaussian_compression_retains_between_group_variance_and_w2() -> None:
    vectors = np.concatenate([np.tile([1., 2.], (30, 1)), np.tile([5., 8.], (3, 1))])
    center, factor = gaussian(vectors)
    raw = (vectors - center).T / np.sqrt(len(vectors) - 1)
    assert factor.shape == (2, 2)
    np.testing.assert_allclose(factor @ factor.T, raw @ raw.T, atol=1e-13)
    assert np.trace(factor @ factor.T) > 0
    other = gaussian(np.array([[1., 1.], [2., 3.], [4., 5.]]))
    assert gaussian_w2((center, factor), other) == pytest.approx(
        gaussian_w2((center, raw), other), abs=1e-12
    )


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("count", [1, 4])
def test_zero_distances_unary_taxa_and_degenerate_reports(tmp_path, method, count) -> None:
    data = Dataset(np.array([f"id_{i}" for i in range(count)]),
                   np.tile([1., 0.], (count, 1)), np.tile(["O", "F", "G", "S"], (count, 1)),
                   {"retained": count})
    path = save_bundle(tmp_path / "input.npz", data)
    report = run(path, tmp_path / "out", families=None, method=method)
    tree = load_tree(tmp_path / "out" / f"{method}.nwk")
    assert leaf_labels(tree) == set(data.ids)
    assert all((node.edge_length or 0) == 0 for node in tree)
    assert report["evaluation"]["embedding_distance"]["normalized_stress"] is None
    assert report["evaluation"]["embedding_distance"]["pairs"] == count * (count - 1) // 2
    assert report["diagnostics"]["unary_nodes"] >= 4
    if method == "weighted" and count > 1:
        assert report["diagnostics"]["gsc_uniform_zero_length_groups"] >= 4


@pytest.mark.parametrize("method", METHODS)
def test_limits_reject_before_pairwise_work(hierarchy, method, monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("Distance allocation must not happen before checking the limit")

    monkeypatch.setattr(centroid, "representative_distances", unexpected)
    monkeypatch.setattr(centroid, "pdist", unexpected)
    with pytest.raises(ValueError, match="max-representative-records"):
        build_tree(hierarchy, method=method, max_representative_records=len(hierarchy.ids) - 1)
    singleton_species = Dataset(hierarchy.ids, hierarchy.embeddings,
                               np.tile(["O", "F", "G", "S"], (len(hierarchy.ids), 1)), {})
    with pytest.raises(ValueError, match="exceeding --max-children=2"):
        build_tree(singleton_species, method=method, max_children=2)
    with pytest.raises(ValueError, match="max_children"):
        build_tree(hierarchy, method=method, max_children=1)
    with pytest.raises(ValueError, match="max_representative_records"):
        build_tree(hierarchy, method=method, max_representative_records=0)


@pytest.mark.parametrize("method", METHODS)
def test_pairwise_matrices_are_only_local(hierarchy, method, monkeypatch) -> None:
    original = pdist

    def bounded(vectors, *args, **kwargs):
        assert len(vectors) <= 4
        return original(vectors, *args, **kwargs)

    monkeypatch.setattr(centroid, "pdist", bounded)
    monkeypatch.setattr("evospaice.tree.representations.pdist", bounded)
    build_tree(hierarchy, method=method, max_children=4)


def test_higher_rank_antipodal_frechet_and_zero_centroid_are_explicit_errors() -> None:
    data = Dataset(
        np.array(["a", "b"]), np.array([[1., 0.], [-1., 0.]]),
        np.array([["O", "F", "G1", "S"], ["O", "F", "G2", "S"]]), {},
    )
    with pytest.raises(ValueError, match="antipodal"):
        build_tree(data, method="frechet")
    with pytest.raises(ValueError, match="centroid is zero"):
        build_tree(data)


def test_invalid_method_backend_and_inputs(hierarchy) -> None:
    for kwargs, match in [
        ({"method": "invalid"}, "Unknown representation"),
        ({"nj_backend": "invalid"}, "Unknown NJ backend"),
        ({"start_rank": 5}, "start_rank"),
    ]:
        with pytest.raises(ValueError, match=match):
            build_tree(hierarchy, **kwargs)
    with pytest.raises(ValueError, match="Unknown representation"):
        build_genus(hierarchy, "invalid")
    with pytest.raises(ValueError, match="exactly one genus"):
        build_genus(hierarchy, "centroid")
    for vectors in [np.zeros_like(hierarchy.embeddings),
                    np.full_like(hierarchy.embeddings, np.nan)]:
        with pytest.raises(ValueError, match="non-finite or zero"):
            build_tree(Dataset(hierarchy.ids, vectors, hierarchy.taxonomy, {}))


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("entrypoint", [["-m", "evospaice.tree.centroid"],
                                       ["-m", "evospaice.cli", "tree", "build"]])
def test_cli_npz_full_hierarchy_outputs(tmp_path, hierarchy, method, entrypoint) -> None:
    path = save_bundle(tmp_path / "input.npz", hierarchy)
    output = tmp_path / "out"
    completed = subprocess.run(
        [sys.executable, *entrypoint, "--embeddings", str(path), "--output-dir", str(output),
         "--all-families", "--method", method, "--pairs", "40"],
        text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads((output / "report.json").read_text())
    assert report["algorithm"]["method"] == method
    assert report["algorithm"]["ranks"] == list(RANKS)
    assert report["algorithm"]["nj_backend"] == "biopython"
    assert report["taxon_counts"]["order"] == 2
    assert report["taxon_counts"]["family"] == 5
    assert report["evaluation"]["embedding_distance"]["pairs"] == 40
    assert leaf_labels(load_tree(output / f"{method}.nwk")) == set(hierarchy.ids)
    assert (output / "selected-records.tsv").is_file()
    assert (output / "evaluated-pairs.tsv").is_file()
    if method == "wasserstein":
        assert report["evaluation"]["target_distance"] == "euclidean"
        assert not report["evaluation"]["cosine_comparison"]["raw_magnitude_comparable"]
        assert "normalized_stress" not in report["evaluation"]["cosine_comparison"]
    else:
        assert report["evaluation"]["target_distance"] == "cosine"


def test_default_centroid_keeps_exact_legacy_tree(hierarchy) -> None:
    def legacy(indices, depth, name):
        if depth == len(RANKS):
            children = [centroid.Subtree(centroid.Clade(name=str(hierarchy.ids[i]),
                                                      branch_length=0.0),
                                        hierarchy.embeddings[i], 1) for i in indices]
        else:
            groups = {}
            for i in indices:
                groups.setdefault(str(hierarchy.taxonomy[i, depth]), []).append(i)
            children = [legacy(group, depth + 1, f"{RANKS[depth]}:{label}")
                        for label, group in sorted(groups.items())]
        return centroid.combine(name, children, Counter(), 512)

    old = legacy(list(range(len(hierarchy.ids))), 0, "butterfly_centroid_baseline")
    default, _ = build_tree(hierarchy)
    explicit, _ = build_tree(hierarchy, method="centroid")
    assert newick(default) == newick(explicit) == newick(Tree(root=old.root, rooted=True))


@pytest.mark.parametrize("arguments, error", [
    (["--method", "invalid"], "invalid choice"),
    (["--max-children", "1"], "max_children"),
    (["--max-representative-records", "0"], "max_representative_records"),
    (["--pairs", "0"], "pair_limit"),
])
def test_cli_rejects_invalid_options_without_output(tmp_path, hierarchy, arguments, error) -> None:
    path = save_bundle(tmp_path / "input.npz", hierarchy)
    output = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "evospaice.tree.centroid", "--embeddings", str(path),
         "--output-dir", str(output), "--all-families", *arguments],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert error in result.stderr
    assert not output.exists()


def test_compare_cli_data_still_uses_shared_builder_and_honest_units(tmp_path) -> None:
    rng = np.random.default_rng(17)
    data = Dataset(np.array([f"r{i}" for i in range(8)]), rng.uniform(.1, 2, (8, 3)),
                   np.array([["O", "Papilionidae", "G", f"S{i // 2}"] for i in range(8)]),
                   {"retained": 8})
    path = save_bundle(tmp_path / "input.npz", data)
    baseline = tmp_path / "baseline"
    run(path, baseline)
    assert cli.main([
        "tree", "compare", "--embeddings", str(path),
        "--metadata", str(baseline / "selected-records.tsv"),
        "--reference", str(baseline / "centroid.nwk"),
        "--genus", "G", "--output-dir", str(tmp_path / "comparison"),
    ]) == 0
    result = json.loads((tmp_path / "comparison" / "comparison.json").read_text())
    assert set(result["methods"]) == set(METHODS) | {"reference"}
    w2 = result["methods"]["wasserstein"]
    assert not w2["cosine_comparison"]["raw_magnitude_comparable"]
    assert w2["cosine_comparison"]["normalized_stress"] is None
    assert w2["native_distance_comparison"]["normalized_stress"] is not None
    assert (tmp_path / "comparison" / "index.html").is_file()
