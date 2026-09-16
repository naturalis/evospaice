from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from Bio.Phylo.BaseTree import Clade

from evospaice.tree.centroid import (
    Subtree,
    build_tree,
    combine,
    load_embeddings,
    run,
    sampled_pairs,
)
from evospaice.validate.compare import leaf_labels, load_tree


def bundle(path: Path, **overrides) -> Path:
    arrays = {
        "ids": np.array([f"record_{i}" for i in range(6)]),
        "embeddings": np.array([
            [1, .1], [1, .2], [.8, .7], [.7, .8], [.1, 1], [.2, 1],
        ]),
        "order": np.array(["Lepidoptera"] * 6),
        "family": np.array(["Nymphalidae"] * 6),
        "genus": np.array(["A"] * 3 + ["B"] * 3),
        "species": np.array(["A one", "A one", "A two", "B one", "B two", "B two"]),
    }
    np.savez(path, **(arrays | overrides))
    return path


def test_filtering_accounts_for_every_record(tmp_path: Path) -> None:
    path = bundle(
        tmp_path / "input.npz",
        family=np.array(["Nymphalidae"] * 5 + ["Geometridae"]),
        species=np.array(["A one", "A one", "A two", "unknown", "B two", "B two"]),
    )
    result = load_embeddings(path, ("Nymphalidae",), {f"record_{i}" for i in range(1, 6)})
    assert result.coverage == {
        "source_records": 6, "outside_selected_families": 1, "not_in_requested_ids": 1,
        "incomplete_taxonomy": 1, "retained": 3,
    }
    assert result.ids.tolist() == ["record_1", "record_2", "record_4"]


def test_centroid_weights_descendant_records_not_child_count() -> None:
    first = Subtree(Clade(name="a"), np.array([2., 1.]), 1)
    second = Subtree(Clade(name="b"), np.array([2., 3.]), 3)
    result = combine("parent", [first, second], Counter(), 10)
    np.testing.assert_allclose(result.centroid, [2, 2.5])
    assert result.records == 4
    assert {leaf.name for leaf in result.root.get_terminals()} == {"a", "b"}


def test_all_families_includes_moths_but_still_requires_complete_taxonomy(
    tmp_path: Path,
) -> None:
    path = bundle(
        tmp_path / "input.npz",
        family=np.array(["Nymphalidae"] * 3 + ["Geometridae", "None", "Geometridae"]),
        species=np.array(["A one", "A one", "A two", "B one", "B two", "None"]),
    )
    data = load_embeddings(path, None)
    assert data.coverage == {
        "source_records": 6, "outside_selected_families": 0,
        "not_in_requested_ids": 0, "incomplete_taxonomy": 2, "retained": 4,
    }
    output = tmp_path / "all-families"
    report = run(path, output, families=None, pair_limit=100)
    assert report["selection"]["families"] is None
    assert report["selection"]["complete_taxonomy_required"]
    assert report["taxon_counts"]["family"] == 2
    assert report["families"] == {"Nymphalidae": 3, "Geometridae": 1}
    assert leaf_labels(load_tree(output / "centroid.nwk")) == set(data.ids)
    filtered = load_embeddings(path, ("Nymphalidae",))
    assert filtered.ids.tolist() == ["record_0", "record_1", "record_2"]


def test_identical_embeddings_and_unary_taxa_are_supported(tmp_path: Path) -> None:
    path = bundle(tmp_path / "input.npz", embeddings=np.tile([1., 0.], (6, 1)))
    data = load_embeddings(path, ("Nymphalidae",))
    tree, diagnostics = build_tree(data)
    assert {leaf.name for leaf in tree.get_terminals()} == set(data.ids)
    assert all((clade.branch_length or 0) == 0 for clade in tree.find_clades())
    assert diagnostics["zero_length_connectors"] > 0
    assert diagnostics["unary_nodes"] > 0


def test_end_to_end_output_and_overwrite_protection(tmp_path: Path) -> None:
    path = bundle(tmp_path / "input.npz")
    output = tmp_path / "result"
    report = run(path, output, pair_limit=100)
    assert report["coverage"]["retained"] == 6
    assert report["evaluation"]["embedding_distance"]["pairs"] == 15
    assert leaf_labels(load_tree(output / "centroid.nwk")) == {
        f"record_{i}" for i in range(6)
    }
    assert (output / "selected-records.tsv").is_file()
    assert (output / "evaluated-pairs.tsv").is_file()
    with pytest.raises(FileExistsError):
        run(path, output)


def test_reference_comparison_uses_exact_same_record_ids(tmp_path: Path) -> None:
    path = bundle(tmp_path / "input.npz")
    first = tmp_path / "first"
    run(path, first, pair_limit=100)
    report = run(
        path, tmp_path / "compared", reference=first / "centroid.nwk", pair_limit=100
    )
    assert report["reference"]["matched_tips"] == 6
    assert report["reference"]["unrooted_topology"]["rf"] == 0
    assert report["reference"]["path_comparison"]["normalized_stress"] < 1e-10


def test_fanout_limit_is_explicit(tmp_path: Path) -> None:
    path = bundle(tmp_path / "input.npz", species=np.array(["A one"] * 3 + ["B one"] * 3))
    data = load_embeddings(path, ("Nymphalidae",))
    with pytest.raises(ValueError, match="exceeding"):
        build_tree(data, max_children=2)


@pytest.mark.parametrize("bad", [np.zeros((6, 2)), np.full((6, 2), np.nan)])
def test_invalid_vectors_are_not_silently_dropped(tmp_path: Path, bad: np.ndarray) -> None:
    path = bundle(tmp_path / "input.npz", embeddings=bad)
    with pytest.raises(ValueError, match="non-finite or zero"):
        load_embeddings(path, ("Nymphalidae",))


def test_pair_sampling_is_reproducible_and_without_duplicates() -> None:
    first = sampled_pairs(100, 1000, 42)
    assert first == sampled_pairs(100, 1000, 42)
    assert len(first) == len(set(first)) == 1000
    assert all(0 <= a < b < 100 for a, b in first)
    with pytest.raises(ValueError, match="positive pair limit"):
        sampled_pairs(100, 0, 42)
