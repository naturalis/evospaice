import csv
import gzip
import json
from pathlib import Path

import dendropy
import pytest

from evospaice.cli import main as cli_main
from evospaice.validate.compare import (
    leaf_labels,
    load_tree,
    prepare_trees,
    root_to_node_lengths,
    tip_to_root_correlation,
    topology_metrics,
)
from evospaice.validate.evaluate import main, read_table


@pytest.fixture
def cli_arguments(tmp_path):
    source = tmp_path / "tree.nwk"
    source.write_text("((A,B),(C,D));")
    return ["--inferred", str(source), "--reference", str(source), "--mode", "unrooted",
            "--output-dir", str(tmp_path / "report"), "--no-tip-to-root-correlation"]


def test_cli_report_and_overwrite(cli_arguments, tmp_path, capsys):
    assert cli_main(["validate", *cli_arguments]) == 0
    output = tmp_path / "report"
    report = json.loads((output / "validation.json").read_text())
    assert report["topology"]["rf"] == 0
    assert report["topology"]["rf_normalized"] == 0
    assert report["branch_lengths"] == "ignored"
    assert report["schema_version"] == 5
    assert "tip_to_root_correlation" not in report
    assert "scipy" not in report["versions"]
    assert report["warnings"]
    assert {path.name for path in output.iterdir()} == {"validation.json", "taxa.csv", "clades.csv"}
    assert json.loads(capsys.readouterr().out) == report["topology"]
    with pytest.raises(SystemExit) as error:
        cli_main(["validate", *cli_arguments])
    assert error.value.code == 2
    assert cli_main(["validate", *cli_arguments, "--overwrite"]) == 0


@pytest.mark.parametrize("input_option,filename,content", [
    ("--inferred", "taxa.csv", "((A,B),(C,D));"),
    ("--reference", "clades.csv", "((A,B),(C,D));"),
    ("--metadata", "validation.json", '{"citation": "keep me"}'),
    ("--inferred", "node_lengths.csv", "((A,B),(C,D));"),
    ("--reference", "tip_to_root_correlation.csv", "((A,B),(C,D));"),
])
def test_outputs_cannot_overwrite_inputs(cli_arguments, tmp_path, input_option, filename, content):
    output = tmp_path / "report"
    output.mkdir()
    source = output / filename
    source.write_text(content)
    with pytest.raises(SystemExit) as error:
        main([*cli_arguments, input_option, str(source), "--overwrite",
              "--tip-to-root-correlation"])
    assert error.value.code == 2
    assert source.read_text() == content
    assert list(output.iterdir()) == [source]


def test_truncated_gzip_is_reported_without_traceback(cli_arguments, tmp_path, capsys):
    source = tmp_path / "tree.nwk.gz"
    source.write_bytes(gzip.compress(b"((A,B),(C,D));")[:-5])
    assert main([*cli_arguments, "--inferred", str(source)]) == 1
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
@pytest.mark.parametrize("filename", ["taxa.csv", "node_lengths.csv",
                                     "tip_to_root_correlation.csv"])
def test_outputs_cannot_overwrite_linked_inputs(cli_arguments, tmp_path, link_kind, filename):
    output = tmp_path / "report"
    output.mkdir()
    source = tmp_path / "tree.nwk"
    before = source.read_bytes()
    destination = output / filename
    if link_kind == "symlink":
        destination.symlink_to(source)
    else:
        destination.hardlink_to(source)
    with pytest.raises(SystemExit) as error:
        main([*cli_arguments, "--overwrite", "--tip-to-root-correlation"])
    assert error.value.code == 2
    assert source.read_bytes() == before
    assert list(output.iterdir()) == [destination]


def test_gzip_report_with_metadata(cli_arguments, tmp_path):
    source = tmp_path / "tree.nwk.gz"
    source.write_bytes(gzip.compress(b"((A,B),(C,D));"))
    metadata = tmp_path / "metadata.json"
    metadata.write_text('{"citation": "reference source"}')
    assert main([*cli_arguments, "--inferred", str(source), "--metadata", str(metadata)]) == 0
    report = json.loads((tmp_path / "report" / "validation.json").read_text())
    assert report["metadata"] == {"citation": "reference source"}
    assert report["inputs"]["metadata"]["path"] == str(metadata)
    assert len(report["inputs"]["metadata"]["sha256"]) == 64


FIXTURE = Path(__file__).parent / "data" / "reference_tree_mock.nwk"
MOCK = FIXTURE.with_name("embedding_tree_mock.nwk")


def tree(text):
    return dendropy.Tree.get(data=text, schema="newick", preserve_underscores=True)


def test_tip_to_root_mock_depths_and_correlation():
    original = {"reference": load_tree(FIXTURE), "inferred": load_tree(MOCK)}
    before = {name: source.as_string(schema="newick") for name, source in original.items()}
    depths = {}
    for name, source in original.items():
        rows, depths[name] = root_to_node_lengths(source, name=name)
        assert rows[0]["root_to_node_sum"] == 0
        assert rows[0]["parent_id"] is None
        assert source.as_string(schema="newick") == before[name]
    assert depths["reference"] == pytest.approx(dict(A=0.07, B=0.08, C=0.32, D=0.35))
    assert depths["inferred"] == pytest.approx(dict(A=0.35, B=0.08, C=0.07, D=0.32))
    result, rows = tip_to_root_correlation(
        list(depths["reference"].items()), list(depths["inferred"].items()),
        retained_taxa=set("ABCD"),
    )
    assert result["rho"] == pytest.approx(-0.4)
    assert result["status"] == "ok"
    assert [row["taxon"] for row in rows] == list("ABCD")
    assert [row["reference_rank"] for row in rows] == [4, 3, 2, 1]
    assert [row["inferred_rank"] for row in rows] == [1, 3, 4, 2]


@pytest.mark.parametrize("mode,raw", [("rooted", 4), ("unrooted", 2)])
def test_rf_known_answer(mode, raw):
    aligned, coverage = prepare_trees(
        {"inferred": tree("((A,B),(C,D));"), "reference": tree("((A,C),(B,D));")}, mode=mode
    )
    result, rows = topology_metrics(aligned["inferred"], aligned["reference"])
    assert result["rf"] == raw
    assert result["rf_normalized"] == 1
    assert result["rf_denominator"] == raw
    assert not {"precision", "recall"} & result.keys()
    assert all(row["origin"] != "both" for row in rows)
    assert len(coverage) == 8


@pytest.mark.parametrize("mode", ["rooted", "unrooted"])
def test_rotation_lengths_and_no_mutation(mode):
    original = tree("((A:1,B:2):3,(C:4,D:5):6):100;")
    before = original.as_string(schema="newick")
    aligned, _ = prepare_trees({"inferred": original,
                                "reference": tree("((D,C),(B,A));")}, mode=mode)
    result, _ = topology_metrics(aligned["inferred"], aligned["reference"])
    assert result["rf"] == 0
    assert result["rf_normalized"] == 0
    assert original.as_string(schema="newick") == before


def test_rf_symmetry_with_partial_resolution():
    aligned, _ = prepare_trees({"inferred": tree("((A,B),(C,D));"),
                                "reference": tree("((A,B),C,D);")}, mode="rooted")
    result, _ = topology_metrics(aligned["inferred"], aligned["reference"])
    assert result["rf"] == 1
    assert result["rf_normalized"] == pytest.approx(1 / 3)
    assert result["rf_denominator"] == 3
    reverse, _ = topology_metrics(aligned["reference"], aligned["inferred"])
    assert reverse["rf"] == result["rf"]
    assert reverse["rf_normalized"] == result["rf_normalized"]


@pytest.mark.parametrize("mode", ["rooted", "unrooted"])
@pytest.mark.parametrize("unresolved", [("inferred",), ("reference",),
                                       ("inferred", "reference")])
def test_unresolved_trees(mode, unresolved):
    aligned, _ = prepare_trees(
        {name: tree("(A,B,C,D);" if name in unresolved else "((A,B),(C,D));")
         for name in ("inferred", "reference")}, mode=mode,
    )
    kind = "clade" if mode == "rooted" else "split"
    message = f"{unresolved[0]} tree must have at least one informative {kind}"
    with pytest.raises(ValueError, match=message):
        topology_metrics(aligned["inferred"], aligned["reference"])


@pytest.mark.parametrize("mode", ["rooted", "unrooted"])
@pytest.mark.parametrize("unresolved", [("inferred",), ("reference",),
                                       ("inferred", "reference")])
def test_cli_unresolved_trees(cli_arguments, tmp_path, capsys, mode, unresolved):
    source = tmp_path / "star.nwk"
    source.write_text("(A,B,C,D);")
    arguments = [*cli_arguments, "--mode", mode]
    for name in unresolved:
        arguments.extend([f"--{name}", str(source)])
    with pytest.raises(SystemExit) as error:
        cli_main(["validate", *arguments])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert f"error: {unresolved[0]} tree must have at least one informative" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("mode", ["rooted", "unrooted"])
@pytest.mark.parametrize("policy", ["selection", "intersection"])
def test_resolution_lost_after_pruning(mode, policy):
    aligned, _ = prepare_trees(
        {"inferred": tree("((A,E),B,C,D);"), "reference": tree("((A,B),(C,D));")},
        mode=mode, taxa_policy="strict" if policy == "selection" else "intersection",
        selected=set("ABCD") if policy == "selection" else None,
    )
    with pytest.raises(ValueError, match="inferred tree must have at least one informative"):
        topology_metrics(aligned["inferred"], aligned["reference"])


def test_strict_intersection_and_mapping():
    trees = {"inferred": tree("((a,B),(C,D));"), "reference": tree("((A,B),(C,D),E);")}
    with pytest.raises(ValueError, match="taxa differ"):
        prepare_trees(trees, mode="rooted")
    aligned, coverage = prepare_trees(trees, mode="rooted", taxa_policy="intersection",
                                      mappings={"inferred": {"a": "A"}})
    assert topology_metrics(aligned["inferred"], aligned["reference"])[0]["rf"] == 0
    assert sum(not row["retained"] for row in coverage) == 1
    with pytest.raises(ValueError, match="unique"):
        prepare_trees(trees, mode="rooted", mappings={"inferred": {"a": "B"}})


@pytest.mark.parametrize("mode", ["rooted", "unrooted"])
def test_unary_nodes_and_selected_taxa(mode):
    aligned, coverage = prepare_trees(
        {"inferred": tree("((((A,B)),(C,D)),E);"), "reference": tree("((A,B),(C,D));")},
        mode=mode, selected=set("ABCD"),
    )
    assert topology_metrics(aligned["inferred"], aligned["reference"])[0]["rf"] == 0
    assert [row["reason"] for row in coverage if not row["retained"]] == ["not_selected"]


def test_loader_bounds_and_labels(tmp_path):
    path = tmp_path / "tree.nwk"
    path.write_text("('BOLD:A_a','with space',A,a);")
    assert len(list(load_tree(path).leaf_node_iter())) == 4
    with pytest.raises(ValueError, match="size limit"):
        load_tree(path, max_bytes=2)
    path.write_text("(A,B);(C,D);")
    with pytest.raises(ValueError, match="exactly one"):
        load_tree(path)


@pytest.mark.parametrize("label", [None, "", " ", 123, "B"])
def test_invalid_leaf_labels(label):
    original = tree("((A,B),(C,D));")
    next(original.leaf_node_iter()).taxon.label = label
    with pytest.raises(ValueError, match="nonempty|unique"):
        leaf_labels(original)


def test_missing_leaf_taxon():
    original = tree("((A,B),(C,D));")
    next(original.leaf_node_iter()).taxon = None
    with pytest.raises(ValueError, match="nonempty"):
        leaf_labels(original)


def test_cli_large_tree_without_tip_cap(cli_arguments, tmp_path):
    source = tmp_path / "tree.nwk"
    labels = [f"taxon_{index}" for index in range(5001)]
    source.write_text("((" + ",".join(labels[:2]) + ")," + ",".join(labels[2:]) + ");")
    assert main(cli_arguments) == 0
    report = json.loads((tmp_path / "report" / "validation.json").read_text())
    assert report["retained_taxa"] == 5001
    assert report["topology"]["rf"] == 0
    assert "limits" not in report


def test_cli_identity_report(tmp_path, capsys):
    from evospaice.cli import main as cli_main

    output = tmp_path / "report"
    arguments = ["validate", "--inferred", str(FIXTURE), "--reference", str(FIXTURE),
                 "--mode", "rooted", "--output-dir", str(output), "--no-tip-to-root-correlation"]
    assert cli_main(arguments) == 0
    report = json.loads((output / "validation.json").read_text())
    assert report["schema_version"] == 5
    assert report["topology"]["rf"] == 0
    assert report["topology"]["rf_normalized"] == 0
    assert report["branch_lengths"] == "ignored"
    assert not {"branches", "diagnostics", "support", "baseline", "diversity"} & report.keys()
    assert not {"f1", "precision", "recall"} & report["topology"].keys()
    assert report["warnings"]
    assert {path.name for path in output.iterdir()} == {"validation.json", "clades.csv", "taxa.csv"}
    assert json.loads(capsys.readouterr().out)["rf"] == 0
    with pytest.raises(SystemExit) as error:
        cli_main(arguments)
    assert error.value.code == 2
    before = (output / "validation.json").read_text()
    assert cli_main(arguments + ["--overwrite"]) == 0
    assert (output / "validation.json").read_text() == before


def test_other_tracks_remain_placeholders(capsys):
    from evospaice.cli import main as cli_main

    assert cli_main(["diversity"]) == 2
    assert "not implemented yet" in capsys.readouterr().err


@pytest.mark.parametrize("mode,raw", [("rooted", 4), ("unrooted", 2)])
@pytest.mark.parametrize("length_metric", [False, True])
def test_cli_mock_comparison(tmp_path, mode, raw, length_metric, capsys):
    output = tmp_path / "out"
    extra = [] if length_metric else ["--no-tip-to-root-correlation"]
    assert main(["--inferred", str(MOCK), "--reference", str(FIXTURE), "--mode", mode,
                 "--output-dir", str(output), *extra]) == 0
    report = json.loads((output / "validation.json").read_text())
    result = report["topology"]
    assert result["rf"] == raw
    assert result["rf_normalized"] == 1
    assert not {"precision", "recall"} & result.keys()
    assert report["schema_version"] == 5
    if length_metric:
        metric = report["tip_to_root_correlation"]
        assert metric["rho"] == pytest.approx(-0.4)
        assert metric["compared_tip_count"] == 4
        assert metric["branch_length_units"] == dict(reference="unknown", inferred="unknown")
        assert metric["root_policy"] == "original_supplied_root_stem_excluded"
        assert report["root_policy"] == ("supplied_root" if mode == "rooted" else "unrooted_splits")
        assert report["branch_lengths"] == dict(rf="ignored", tip_to_root_correlation="used")
        assert report["versions"]["scipy"]
        assert {path.name for path in output.iterdir()} == {
            "validation.json", "taxa.csv", "clades.csv", "node_lengths.csv",
            "tip_to_root_correlation.csv",
        }
        assert "tip-to-root-correlation:" in capsys.readouterr().out
    else:
        assert "tip_to_root_correlation" not in report
        assert json.loads(capsys.readouterr().out) == result


@pytest.mark.parametrize("option", ["--length-mode", "--distances", "--embedding-vectors",
                                    "--replicates", "--samples", "--baseline-tree",
                                    "--support-field"])
def test_removed_options_rejected(tmp_path, option, capsys):
    with pytest.raises(SystemExit) as error:
        main(["--inferred", str(FIXTURE), "--reference", str(FIXTURE), "--mode", "rooted",
              "--output-dir", str(tmp_path), option, "unused"])
    assert error.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


@pytest.mark.parametrize("content", ["label\nA\n", "taxon\ttaxon\nA\tA\n", "taxon\n",
                                     "taxon\n \n", "taxon\textra\nA\n"])
def test_invalid_taxa_table(tmp_path, content):
    path = tmp_path / "taxa.tsv"
    path.write_text(content)
    with pytest.raises(ValueError):
        read_table(path, {"taxon"})


def test_cli_mapping_and_selection(tmp_path):
    inferred = tmp_path / "inferred.nwk"
    inferred.write_text("((a,B),(C,D),E);")
    mapping = tmp_path / "map.tsv"
    mapping.write_text("tree\tlabel\ttaxon\ninferred\ta\tA\n")
    selected = tmp_path / "taxa.tsv"
    selected.write_text("taxon\nA\nB\nC\nD\n")
    output = tmp_path / "out"
    assert main(["--inferred", str(inferred), "--reference", str(FIXTURE), "--mode", "unrooted",
                 "--output-dir", str(output), "--taxon-map", str(mapping),
                 "--taxa-file", str(selected), "--no-tip-to-root-correlation"]) == 0
    report = json.loads((output / "validation.json").read_text())
    assert report["topology"]["rf"] == 0
    assert report["retained_taxa"] == 4
    assert report["coverage"]["inferred"]["original"] == 5


@pytest.fixture
def length_arguments(cli_arguments, tmp_path):
    (tmp_path / "tree.nwk").write_text("((A:1,B:2):1,(C:3,D:4):1):99;")
    return [arg for arg in cli_arguments if arg != "--no-tip-to-root-correlation"]


@pytest.mark.parametrize("scale", [1, 10])
def test_tip_to_root_identity_scaling_and_order(scale):
    reference = [("A", 1.0), ("B", 3.0), ("C", 2.0)]
    inferred = [(label, value * scale) for label, value in reversed(reference)]
    result, rows = tip_to_root_correlation(reference, inferred, retained_taxa=set("ABC"))
    assert result["rho"] == pytest.approx(1)
    assert [row["reference_rank"] for row in rows] == [3, 1, 2]
    assert [row["inferred_rank"] for row in rows] == [3, 1, 2]


def test_tip_to_root_ties_match_scipy():
    from scipy.stats import spearmanr

    result, rows = tip_to_root_correlation(
        list(zip("ABCD", [1, 1, 3, 4], strict=True)),
        list(zip("ABCD", [4, 2, 2, 1], strict=True)),
        retained_taxa=set("ABCD"),
    )
    assert result["rho"] == pytest.approx(spearmanr([1, 1, 3, 4], [4, 2, 2, 1]).statistic)
    assert [row["reference_rank"] for row in rows] == [3.5, 3.5, 2, 1]
    assert [row["inferred_rank"] for row in rows] == [1, 2.5, 2.5, 4]


@pytest.mark.parametrize("constant", [("reference",), ("inferred",), ("reference", "inferred")])
def test_cli_constant_depths_are_valid_undefined(length_arguments, tmp_path, capsys, constant):
    source = tmp_path / "constant.nwk"
    source.write_text("((A:1,B:1):1,(C:1,D:1):1);")
    arguments = list(length_arguments)
    for name in constant:
        arguments.extend([f"--{name}", str(source)])
    assert main(arguments) == 0
    output = tmp_path / "report"
    serialized = (output / "validation.json").read_text()
    report = json.loads(serialized)
    metric = report["tip_to_root_correlation"]
    assert metric["rho"] is None
    assert '"rho": null' in serialized
    assert "NaN" not in serialized
    assert metric["status"] == "undefined"
    assert metric["undefined_reason"] == "Constant tip-to-root lengths in " + " and ".join(constant)
    assert report["topology"]["rf"] == 0
    with (output / "tip_to_root_correlation.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    for name in constant:
        assert {float(row[f"{name}_rank"]) for row in rows} == {2.5}
    with (output / "node_lengths.csv").open(newline="") as handle:
        assert len(list(csv.DictReader(handle))) == 14
    assert "tip-to-root-correlation: undefined" in capsys.readouterr().out


@pytest.mark.parametrize("bad", [None, -1.0, float("nan"), float("inf"), float("-inf")])
def test_root_to_node_invalid_edges(bad):
    source = tree("((A:1,B:2):1,C:3);")
    next(source.leaf_node_iter()).edge_length = bad
    with pytest.raises(ValueError, match="reference: node 2 .*A.*finite and nonnegative"):
        root_to_node_lengths(source, name="reference")


@pytest.mark.parametrize("stem", ["100", "-1", "nan", "inf"])
def test_root_to_node_zero_edges_and_ignored_stem(stem):
    source = tree(f"((A:0,B:1)X:0,(C:2,D:3)X:0)X:{stem};")
    rows, depths = root_to_node_lengths(source, name="reference")
    assert depths == dict(A=0, B=1, C=2, D=3)
    assert [row["node_id"] for row in rows] == list(range(7))
    assert [row["parent_id"] for row in rows] == [None, 0, 1, 1, 0, 4, 4]
    assert rows[0]["root_to_node_sum"] == 0
    assert sum(row["original_label"] == "X" for row in rows) == 3


def test_root_to_node_deep_unary_and_unlabelled_nodes():
    source = dendropy.Tree()
    current = source.seed_node
    for _ in range(2500):
        current = current.new_child(edge_length=1.0)
    for label, length in (("A", 1), ("B", 2), ("C", 3)):
        current.new_child(taxon=source.taxon_namespace.require_taxon(label=label),
                  edge_length=length)
    rows, depths = root_to_node_lengths(source, name="inferred")
    assert depths == dict(A=2501, B=2502, C=2503)
    assert len(rows) == 2504
    assert all(row["original_label"] is None for row in rows[:-3])
    assert len({row["node_id"] for row in rows}) == len(rows)


@pytest.mark.parametrize("name", ["reference", "inferred"])
@pytest.mark.parametrize("bad", ["", ":-1", ":nan", ":inf", ":-inf", ":1e309"])
def test_cli_invalid_excluded_lengths_only_rejected_when_enabled(
    length_arguments, tmp_path, capsys, name, bad,
):
    source = tmp_path / "invalid.nwk"
    source.write_text(f"((A:1,B:2):1,(C:3,D:4):1,E{bad});")
    arguments = [*length_arguments, f"--{name}", str(source), "--taxa-policy", "intersection"]
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
    assert not (tmp_path / "report").exists()
    assert f"{name}: node 7 (label='E')" in capsys.readouterr().err
    assert main([*arguments, "--no-tip-to-root-correlation"]) == 0


def test_cli_cumulative_overflow(length_arguments, tmp_path, capsys):
    (tmp_path / "tree.nwk").write_text("((A:1e308,B:2):1e308,(C:3,D:4):1);")
    with pytest.raises(SystemExit) as error:
        main(length_arguments)
    assert error.value.code == 2
    assert "inferred: node 2 (label='A'): non-finite cumulative" in capsys.readouterr().err
    assert not (tmp_path / "report").exists()


def test_tip_to_root_minimum_and_cli_no_output(length_arguments, tmp_path):
    with pytest.raises(ValueError, match="at least three"):
        tip_to_root_correlation([("A", 1), ("B", 2)], [("A", 2), ("B", 1)],
                                       retained_taxa=set("AB"))
    (tmp_path / "tree.nwk").write_text("(A:1,B:2);")
    with pytest.raises(SystemExit) as error:
        main([*length_arguments, "--mode", "rooted"])
    assert error.value.code == 2
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("bad", [[("A", 1), ("B", 2)],
                                 [("A", 1), ("B", 2), ("B", 3)],
                                 [("A", 1), ("B", 2), ("D", 3)]])
@pytest.mark.parametrize("name", ["reference", "inferred", "both"])
def test_tip_to_root_rejects_invalid_identities(bad, name):
    valid = [("A", 1), ("B", 2), ("C", 3)]
    with pytest.raises(ValueError, match="canonical tip IDs"):
        tip_to_root_correlation(
            bad if name in {"reference", "both"} else valid,
            bad if name in {"inferred", "both"} else valid,
            retained_taxa=set("ABC"),
        )


@pytest.mark.parametrize("defect", ["missing", "duplicate", "unexpected", "both_missing"])
def test_cli_rejects_coverage_identity_defects(length_arguments, tmp_path, monkeypatch, defect):
    from evospaice.validate import evaluate

    def damaged_coverage(*args, **kwargs):
        aligned, rows = prepare_trees(*args, **kwargs)
        if defect in {"missing", "both_missing"}:
            rows = [row for row in rows if not (
                row["taxon"] == "A" and (row["tree"] == "reference" or defect == "both_missing")
            )]
        elif defect == "duplicate":
            rows.append(dict(rows[0]))
        else:
            rows[0]["taxon"] = "unexpected"
        return aligned, rows

    monkeypatch.setattr(evaluate, "prepare_trees", damaged_coverage)
    with pytest.raises(SystemExit) as error:
        main(length_arguments)
    assert error.value.code == 2
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("mode", ["rooted", "unrooted"])
@pytest.mark.parametrize("policy", ["strict", "intersection"])
def test_cli_length_mapping_selection_preserves_original_root(tmp_path, mode, policy):
    source = tmp_path / "inferred.nwk"
    source.write_text("(((D:4,C:3):1,(B:2,a:1):1):10,E:2):100;")
    reference = tmp_path / "reference.nwk"
    reference.write_text("((A:1,B:2):1,(C:3,D:4):1,F:1);")
    mapping = tmp_path / "map.tsv"
    mapping.write_text("tree\tlabel\ttaxon\ninferred\ta\tA\n")
    selected = tmp_path / "selected.tsv"
    selected.write_text("taxon\nA\nB\nC\nD\n")
    output = tmp_path / "report"
    arguments = ["--reference", str(reference), "--inferred", str(source), "--mode", mode,
                 "--output-dir", str(output), "--taxa-policy", policy,
                 "--taxon-map", str(mapping)]
    if policy == "strict":
        arguments.extend(["--taxa-file", str(selected)])
    before = {path: path.read_bytes() for path in (source, reference, mapping, selected)}
    assert main(arguments) == 0
    report = json.loads((output / "validation.json").read_text())
    assert report["topology"]["rf"] == 0
    assert report["tip_to_root_correlation"]["rho"] == pytest.approx(1)
    with (output / "tip_to_root_correlation.csv").open(newline="") as handle:
        tips = list(csv.DictReader(handle))
    assert [row["taxon"] for row in tips] == list("ABCD")
    assert [float(row["inferred_sum"]) for row in tips] == [12, 13, 14, 15]
    assert [float(row["reference_sum"]) for row in tips] == [2, 3, 4, 5]
    with (output / "node_lengths.csv").open(newline="") as handle:
        nodes = list(csv.DictReader(handle))
    with (output / "taxa.csv").open(newline="") as handle:
        coverage = list(csv.DictReader(handle))
    for row in coverage:
        node = next(node for node in nodes if node["tree"] == row["tree"]
                    and node["original_label"] == row["label"] and node["node_kind"] == "tip")
        if row["retained"] == "True":
            tip = next(tip for tip in tips if tip["taxon"] == row["taxon"])
            assert float(node["root_to_node_sum"]) == float(tip[f"{row['tree']}_sum"])
    assert {row["original_label"] for row in nodes if row["node_kind"] == "tip"} >= {"E", "F", "a"}
    first_outputs = {path.name: path.read_bytes() for path in output.iterdir()}
    assert main([*arguments, "--overwrite"]) == 0
    assert {path.name: path.read_bytes() for path in output.iterdir()} == first_outputs
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("units", [
    {}, {"reference": "substitutions/site"},
    {"reference": "substitutions/site", "inferred": "embedding distance"},
])
def test_cli_length_units_metadata(length_arguments, tmp_path, units):
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(dict(branch_length_units=units)))
    assert main([*length_arguments, "--metadata", str(metadata)]) == 0
    report = json.loads((tmp_path / "report" / "validation.json").read_text())
    assert report["tip_to_root_correlation"]["branch_length_units"] == {
        name: units.get(name, "unknown") for name in ("reference", "inferred")
    }


@pytest.mark.parametrize("units", [None, [], "unknown", {"reference": 12}, {"inferred": ""}])
def test_cli_invalid_units_metadata(length_arguments, tmp_path, units):
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps(dict(branch_length_units=units)))
    with pytest.raises(SystemExit) as error:
        main([*length_arguments, "--metadata", str(metadata)])
    assert error.value.code == 2
    assert not (tmp_path / "report").exists()


def test_cli_serialization_finishes_before_output_writes(length_arguments, tmp_path, monkeypatch):
    from evospaice.validate import evaluate

    serialize = evaluate._serialize_csv

    def fail_tip_serialization(rows, fields):
        if "reference_rank" in fields:
            raise ValueError("Cannot serialize tip ranks")
        return serialize(rows, fields)

    monkeypatch.setattr(evaluate, "_serialize_csv", fail_tip_serialization)
    with pytest.raises(SystemExit) as error:
        main(length_arguments)
    assert error.value.code == 2
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("mode", ["rooted", "unrooted"])
def test_cli_correlation_only_ignores_rf_requirements(length_arguments, tmp_path, capsys, mode):
    (tmp_path / "tree.nwk").write_text("(A:1,B:2,C:3);")
    assert main([*length_arguments, "--no-rf", "--mode", mode]) == 0
    output = tmp_path / "report"
    report = json.loads((output / "validation.json").read_text())
    assert report["tip_to_root_correlation"]["rho"] == pytest.approx(1)
    assert report["retained_taxa"] == 3
    assert not {"topology", "mode", "root_policy"} & report.keys()
    assert report["branch_lengths"] == dict(tip_to_root_correlation="used")
    assert {path.name for path in output.iterdir()} == {
        "validation.json", "taxa.csv", "node_lengths.csv", "tip_to_root_correlation.csv",
    }
    assert capsys.readouterr().out == "tip-to-root-correlation: 1.0\n"


def test_cli_cannot_disable_both_metrics(length_arguments, tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        main([*length_arguments, "--no-rf", "--no-tip-to-root-correlation"])
    assert error.value.code == 2
    assert "At least one metric must be enabled" in capsys.readouterr().err
    assert not (tmp_path / "report").exists()


def test_cli_default_requires_lengths(cli_arguments, tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        main([arg for arg in cli_arguments if arg != "--no-tip-to-root-correlation"])
    assert error.value.code == 2
    assert "edge length must be finite and nonnegative" in capsys.readouterr().err
    assert not (tmp_path / "report").exists()


def test_cli_correlation_only_still_requires_three_tips(length_arguments, tmp_path, capsys):
    (tmp_path / "tree.nwk").write_text("(A:1,B:2);")
    with pytest.raises(SystemExit) as error:
        main([*length_arguments, "--no-rf"])
    assert error.value.code == 2
    assert "tip-to-root-correlation comparison requires at least 3" in capsys.readouterr().err
    assert not (tmp_path / "report").exists()