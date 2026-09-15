import gzip
import json
from pathlib import Path

import dendropy
import pytest

from evospaice.cli import main as cli_main
from evospaice.validate.compare import leaf_labels, load_tree, prepare_trees, topology_metrics
from evospaice.validate.evaluate import main, read_table


@pytest.fixture
def cli_arguments(tmp_path):
    source = tmp_path / "tree.nwk"
    source.write_text("((A,B),(C,D));")
    return ["--inferred", str(source), "--reference", str(source), "--mode", "unrooted",
            "--output-dir", str(tmp_path / "report")]


def test_cli_report_and_overwrite(cli_arguments, tmp_path, capsys):
    assert cli_main(["validate", *cli_arguments]) == 0
    output = tmp_path / "report"
    report = json.loads((output / "validation.json").read_text())
    assert report["topology"]["rf"] == 0
    assert report["topology"]["rf_normalized"] == 0
    assert not {"precision", "recall", "undefined_reasons"} & report["topology"].keys()
    assert report["branch_lengths"] == "ignored"
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
])
def test_outputs_cannot_overwrite_inputs(cli_arguments, tmp_path, input_option, filename, content):
    output = tmp_path / "report"
    output.mkdir()
    source = output / filename
    source.write_text(content)
    with pytest.raises(SystemExit) as error:
        main([*cli_arguments, input_option, str(source), "--overwrite"])
    assert error.value.code == 2
    assert source.read_text() == content


def test_truncated_gzip_is_reported_without_traceback(cli_arguments, tmp_path, capsys):
    source = tmp_path / "tree.nwk.gz"
    source.write_bytes(gzip.compress(b"((A,B),(C,D));")[:-5])
    assert main([*cli_arguments, "--inferred", str(source)]) == 1
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_outputs_cannot_overwrite_linked_inputs(cli_arguments, tmp_path, link_kind):
    output = tmp_path / "report"
    output.mkdir()
    source = tmp_path / "tree.nwk"
    before = source.read_bytes()
    destination = output / "taxa.csv"
    if link_kind == "symlink":
        destination.symlink_to(source)
    else:
        destination.hardlink_to(source)
    with pytest.raises(SystemExit) as error:
        main([*cli_arguments, "--overwrite"])
    assert error.value.code == 2
    assert source.read_bytes() == before


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


FIXTURE = Path(__file__).parent / "data" / "reference_tree.nwk"
MOCK = FIXTURE.with_name("embedding_tree_mock.nwk")


def tree(text):
    return dendropy.Tree.get(data=text, schema="newick", preserve_underscores=True)


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
                 "--mode", "rooted", "--output-dir", str(output)]
    assert cli_main(arguments) == 0
    report = json.loads((output / "validation.json").read_text())
    assert report["schema_version"] == 4
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
def test_cli_mock_comparison(tmp_path, mode, raw):
    output = tmp_path / "out"
    assert main(["--inferred", str(MOCK), "--reference", str(FIXTURE), "--mode", mode,
                 "--output-dir", str(output)]) == 0
    result = json.loads((output / "validation.json").read_text())["topology"]
    assert result["rf"] == raw
    assert result["rf_normalized"] == 1
    assert not {"precision", "recall"} & result.keys()


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
                 "--taxa-file", str(selected)]) == 0
    report = json.loads((output / "validation.json").read_text())
    assert report["topology"]["rf"] == 0
    assert report["retained_taxa"] == 4
    assert report["coverage"]["inferred"]["original"] == 5