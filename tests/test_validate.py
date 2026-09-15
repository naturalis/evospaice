import itertools

import dendropy
import pytest

from evospaice.validate.compare import (
    PathDistances,
    branch_metrics,
    prepare_trees,
    sample_pairs,
    topology_metrics,
)


def tree(text):
    return dendropy.Tree.get(data=text, schema="newick", preserve_underscores=True)


@pytest.mark.parametrize("mode,raw", [("rooted", 4), ("unrooted", 2)])
def test_rf_known_answer(mode, raw):
    aligned, coverage, qc = prepare_trees(
        {"inferred": tree("((A,B),(C,D));"), "reference": tree("((A,C),(B,D));")}, mode=mode
    )
    result, rows = topology_metrics(aligned["inferred"], aligned["reference"])
    assert result["rf"] == raw
    assert result["rf_normalized"] == 1
    assert result["precision"] == result["recall"] == 0
    assert all(row["status"] == "conflicting" for row in rows)
    assert len(coverage) == 8
    assert not qc["inferred"]["valid"]


@pytest.mark.parametrize("mode", ["rooted", "unrooted"])
def test_rotation_and_no_mutation(mode):
    original = tree("((A:1,B:2):3,(C:4,D:5):6):100;")
    before = original.as_string(schema="newick")
    aligned, _, _ = prepare_trees({"inferred": original,
                                  "reference": tree("((D:5,C:4):6,(B:2,A:1):3);")}, mode=mode)
    result, _ = topology_metrics(aligned["inferred"], aligned["reference"])
    assert result["rf"] == 0
    assert result["precision"] == result["recall"] == 1
    assert original.as_string(schema="newick") == before


def test_unresolved_not_conflicting():
    aligned, _, _ = prepare_trees({"inferred": tree("((A,B),(C,D));"),
                                  "reference": tree("(A,B,C,D);")}, mode="rooted")
    result, rows = topology_metrics(aligned["inferred"], aligned["reference"])
    assert result["recall"] is None
    assert all(row["status"] == "compatible_unresolved" for row in rows)


def test_strict_intersection_and_mapping():
    trees = {"inferred": tree("((a,B),(C,D));"), "reference": tree("((A,B),(C,D),E);")}
    with pytest.raises(ValueError, match="taxa differ"):
        prepare_trees(trees, mode="rooted")
    aligned, coverage, _ = prepare_trees(trees, mode="rooted", taxa_policy="intersection",
                                        mappings={"inferred": {"a": "A"}})
    assert topology_metrics(aligned["inferred"], aligned["reference"])[0]["rf"] == 0
    assert sum(not row["retained"] for row in coverage) == 1
    with pytest.raises(ValueError, match="unique"):
        prepare_trees(trees, mode="rooted", mappings={"inferred": {"a": "B"}})


def test_sample_pairs():
    labels = list("ABCDE")
    assert sample_pairs(labels) == list(itertools.combinations(labels, 2))
    assert sample_pairs(labels, 3, 12) == sample_pairs(labels, 3, 12)
    assert len(set(sample_pairs(labels, 3))) == 3


def test_branch_scale_and_path():
    aligned, _, qc = prepare_trees(
        {"inferred": tree("((A:2,B:4):6,(C:8,D:10):12);"),
         "reference": tree("((A:1,B:2):3,(C:4,D:5):6);")}, mode="rooted"
    )
    first, second = aligned["inferred"], aligned["reference"]
    assert PathDistances(second).distance("A", "D") == 15
    pairs = sample_pairs(list("ABCD"))
    with pytest.raises(ValueError, match="matching units"):
        branch_metrics(first, second, pairs, length_mode="raw")
    result, _ = branch_metrics(first, second, pairs, original_qc=qc)
    assert result["patristic"]["pearson"] == pytest.approx(1)
    assert result["branch_score_l2"] is None
    result, _ = branch_metrics(first, second, pairs, length_mode="total-length")
    assert result["branch_score_l2"] == 0
    assert result["patristic"]["rmse"] == 0


def test_missing_lengths_remain_topology_only():
    aligned, _, qc = prepare_trees({"inferred": tree("((A,B),(C,D));"),
                                  "reference": tree("((A,B),(C,D));")}, mode="rooted")
    result, rows = branch_metrics(aligned["inferred"], aligned["reference"], [], original_qc=qc)
    assert result["reason"] == "invalid_or_missing_lengths"
    assert rows == []


def test_rooted_basal_path_preserved():
    aligned, _, _ = prepare_trees(
        {"inferred": tree("(((A:1,B:2):3,C:4):5,D:6);"),
         "reference": tree("((A:1,B:2):3,C:4);")},
        mode="rooted", taxa_policy="intersection",
    )
    assert PathDistances(aligned["inferred"]).distance("A", "C") == 8
    assert topology_metrics(aligned["inferred"], aligned["reference"])[0]["rf"] == 0
    metrics, _ = branch_metrics(
        aligned["inferred"], aligned["reference"], [("A", "C")], length_mode="raw",
        inferred_units="test", reference_units="test", units_evidence="fixture",
    )
    assert metrics["branch_score_l2"] == 5
    assert metrics["weighted_rf_l1"] == 5


def test_cli_identity_report(tmp_path):
    import json
    from pathlib import Path

    from evospaice.cli import main

    fixture = Path(__file__).parent / "data" / "diversity_tree.nwk"
    output = tmp_path / "report"
    arguments = ["validate", "--inferred", str(fixture), "--reference", str(fixture),
                 "--mode", "rooted", "--output-dir", str(output), "--length-mode", "raw",
                 "--inferred-units", "test", "--reference-units", "test",
                 "--units-evidence", "synthetic fixture"]
    assert main(arguments) == 0
    report = json.loads((output / "validation.json").read_text())
    assert report["topology"]["rf"] == 0
    assert report["branches"]["branch_score_l2"] == 0
    assert report["diagnostics"]["status"] == "not_evaluated"
    assert report["warnings"]
    assert (output / "clades.csv").is_file()
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2


def test_loader_bounds_and_labels(tmp_path):
    from evospaice.validate.compare import load_tree

    path = tmp_path / "tree.nwk"
    path.write_text("('BOLD:A_a','with space',A,a);")
    loaded = load_tree(path)
    assert len(list(loaded.leaf_node_iter())) == 4
    with pytest.raises(ValueError, match="tip limit"):
        load_tree(path, max_tips=3)
    with pytest.raises(ValueError, match="size limit"):
        load_tree(path, max_bytes=2)
    path.write_text("(A,B);(C,D);")
    with pytest.raises(ValueError, match="exactly one"):
        load_tree(path)


def test_support_filter_only_changes_topology():
    from evospaice.validate.compare import support_view

    aligned, _, _ = prepare_trees(
        {"inferred": tree("((A:1,B:1)90:2,(C:1,D:1)40:2);")}, mode="rooted"
    )
    original = aligned["inferred"]
    before = original.as_string(schema="newick")
    view, support, collapsed = support_view(original, field="label", scale="percent", minimum=.5)
    assert collapsed == 1
    assert sorted(support.values()) == [.4, .9]
    assert topology_metrics(view, original)[0]["rf"] == 1
    assert before == original.as_string(schema="newick")


def test_full_evaluation_workflow(tmp_path):
    import csv
    import json
    from pathlib import Path

    from evospaice.validate.evaluate import main

    fixture = Path(__file__).parent / "data" / "diversity_tree.nwk"
    samples = fixture.with_name("diversity_samples.tsv")
    aligned, _, _ = prepare_trees({"tree": tree(fixture.read_text())}, mode="rooted")
    paths = PathDistances(aligned["tree"])
    distances = tmp_path / "distances.tsv"
    with distances.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["taxon_a", "taxon_b", "embedding_distance", "kmer_distance"])
        for first, second in itertools.combinations("ABCD", 2):
            distance = paths.distance(first, second)
            writer.writerow([first, second, distance, distance * 2])
    replicates = tmp_path / "replicates.nwk"
    replicates.write_text("((A,B),(C,D));((A,B),(C,D));((A,C),(B,D));")
    output = tmp_path / "validation"
    arguments = [
        "--inferred", str(fixture), "--reference", str(fixture), "--mode", "rooted",
        "--output-dir", str(output), "--distances", str(distances),
        "--samples", str(samples), "--replicates", str(replicates),
        "--replicate-kind", "bootstrap", "--replicate-method", "synthetic test replicates",
        "--baseline-tree", str(fixture), "--embedding-fit", "--embedding-units", "test",
        "--inferred-units", "test", "--length-mode", "total-length",
    ]
    assert main(arguments) == 0
    report = json.loads((output / "validation.json").read_text())
    assert report["diagnostics"]["reconstruction_fit"]["rmse"] == 0
    assert report["diagnostics"]["kmer_control"] == "evaluated"
    assert report["baseline"]["topology"]["rf"] == 0
    assert report["diversity"]["pd"]["rmse"] == 0
    assert all(row["support"] == pytest.approx(2 / 3) for row in report["support"]["clades"])
    with (output / "diversity_alpha_comparison.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 5
    with (output / "diversity_beta_comparison.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 10
    before = (output / "validation.json").read_text()
    assert main(arguments + ["--overwrite"]) == 0
    assert (output / "validation.json").read_text() == before


@pytest.mark.parametrize("mode", ["rooted", "unrooted"])
def test_sampled_paths_do_not_build_all_pairs(mode, monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("Full taxon matrix must not be constructed")

    monkeypatch.setattr(dendropy.Tree, "phylogenetic_distance_matrix", prohibited)
    original = tree("((A:1,B:2):3,(C:4,D:5):6);")
    aligned, _, _ = prepare_trees({"inferred": original, "reference": original}, mode=mode)
    pairs = sample_pairs(list("ABCD"), max_pairs=2, seed=5)
    result, rows = branch_metrics(aligned["inferred"], aligned["reference"], pairs)
    assert result["patristic"]["count"] == len(rows) == 2
    assert all(row["inferred_distance"] == row["reference_distance"] for row in rows)


def test_support_filter_cli(tmp_path):
    import json

    from evospaice.validate.evaluate import main

    reference = tmp_path / "reference.nwk"
    reference.write_text("((A:1,B:1)90:2,(C:1,D:1)40:2);")
    output = tmp_path / "out"
    assert main([
        "--inferred", str(reference), "--reference", str(reference), "--mode", "rooted",
        "--output-dir", str(output), "--support-field", "label", "--support-scale", "percent",
        "--min-reference-support", ".5", "--length-mode", "total-length",
    ]) == 0
    report = json.loads((output / "validation.json").read_text())
    assert report["support_filter"]["collapsed"] == 1
    assert report["topology"]["rf"] == 1
    assert report["branches"]["branch_score_l2"] == 0