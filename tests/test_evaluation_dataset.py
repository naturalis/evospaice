import csv
from pathlib import Path

import dendropy
import pytest
from dendropy.utility.error import DataParseError

from evospaice.validate import evaluation_dataset
from evospaice.validate.evaluation_dataset import (
    MST_COLUMNS,
    OUTPUT_COLUMNS,
    DatasetSummary,
    build_evaluation_dataset,
    iter_leaf_rows,
    main,
)

HEADER = (
    "Source_ID,Source_Family,Source_Genus,Source_Species,"
    "Target_ID,Target_Family,Target_Genus,Target_Species,Distance\n"
)
BASIC_EDGE = "A,Family,Genus,Species,B,Other family,Other genus,None,0.1\n"


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    newick = tmp_path / "tree.tre"
    mst_csv = tmp_path / "mst.csv"
    output = tmp_path / "evaluation.csv"
    newick.write_text("(A:0.1,B:0.2);", encoding="utf-8")
    mst_csv.write_text(HEADER + BASIC_EDGE, encoding="utf-8")
    return newick, mst_csv, output


def read_output(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(OUTPUT_COLUMNS)
        return list(reader)


def read_newick_path(text: str) -> list[dendropy.Node]:
    tree = dendropy.Tree.get(data=text, schema="newick", suppress_leaf_node_taxa=True)
    nodes = list(tree.preorder_node_iter())
    assert all(len(node.child_nodes()) == 1 for node in nodes[:-1])
    assert nodes[-1].is_leaf()
    assert all(not node.annotations and not node.comments for node in nodes)
    return nodes


def test_join_uses_only_source_ids_once_and_preserves_tree_order(inputs):
    newick, mst_csv, output = inputs
    newick.write_text(
        "((A:0.1,B:0.2)Inner:0.3,(C:0.4,D:0.5):0.6)Root:9.0;",
        encoding="utf-8",
    )
    a = ["A", "Family,A", "G_A", "Species 'A'"]
    outside = ["outside", "Other", "Other", "Other"]
    with mst_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER.strip().split(","))
        writer.writerows(
            [
                ["D", "None", "", "None", "A", "Foreign family", "Foreign genus", "Foreign", "0.2"],
                [*outside, "B", "FamB", "GenB", "SpB", "0.3"],
                [*a, *outside, "0.4"],
                [*a, "B", "Different family", "Different genus", "Different species", "0.5"],
            ]
        )
    original_tree = newick.read_bytes()
    original_mst = mst_csv.read_bytes()

    summary = build_evaluation_dataset(newick, mst_csv, output)

    assert summary == DatasetSummary(total_leaves=4, matched_leaves=2)
    rows = read_output(output)
    original_columns = OUTPUT_COLUMNS[:10]
    assert [{column: row[column] for column in original_columns} for row in rows] == [
        dict(zip(original_columns, values, strict=True))
        for values in [
            (
                "A",
                "0.1",
                "0.4",
                "2",
                "Inner",
                "Inner",
                "Root > Inner",
                "Family,A",
                "G_A",
                "Species 'A'",
            ),
            ("D", "0.5", "1.1", "2", "", "Root", "Root", "None", "", "None"),
        ]
    ]
    assert rows[0]["tree_newick"] == "((A:0.1)Inner:0.3)Root:9.0;"
    assert rows[1]["tree_newick"] == "((D:0.5):0.6)Root:9.0;"
    tree_path = read_newick_path(rows[1]["tree_newick"])
    assert [node.label for node in tree_path] == ["Root", None, "D"]
    assert [node.edge_length for node in tree_path] == [9.0, 0.6, 0.5]
    taxonomy_path = read_newick_path(rows[0]["taxonomy_newick"])
    assert [node.label for node in taxonomy_path] == ["Family,A", "G_A", "Species 'A'", "A"]
    assert all(node.edge_length is None for node in taxonomy_path)
    assert rows[1]["taxonomy_newick"] == "(((D)));"
    assert [node.label for node in read_newick_path(rows[1]["taxonomy_newick"])] == [
        None,
        None,
        None,
        "D",
    ]
    assert newick.read_bytes() == original_tree
    assert mst_csv.read_bytes() == original_mst
    assert set(output.parent.iterdir()) == {newick, mst_csv, output}


def test_quoted_labels_underscores_case_and_numeric_internal_labels(inputs):
    newick, _, _ = inputs
    newick.write_text(
        "('a_b':1e-2,('A,B':0.0,'O''Brien':-0.2)'quoted parent':2e-2,"
        "A:0.3,a:0.4)95[&note=example];",
        encoding="utf-8",
    )

    rows = list(iter_leaf_rows(newick))

    assert [row["leaf_id"] for row in rows] == ["a_b", "A,B", "O'Brien", "A", "a"]
    assert rows[0]["branch_length"] == "0.01"
    assert rows[0]["ancestor_labels"] == "95"
    assert rows[1]["branch_length"] == "0.0"
    assert rows[1]["distance_from_root"] == "0.02"
    assert rows[2]["distance_from_root"] == "-0.18"
    assert rows[2]["ancestor_labels"] == "95 > quoted parent"
    for row in rows:
        nodes = read_newick_path(row["tree_newick"])
        assert nodes[-1].label == row["leaf_id"]
        assert len(nodes) - 1 == int(row["depth"])
        assert nodes[0].label == "95"
    nodes = read_newick_path(rows[2]["tree_newick"])
    assert [node.label for node in nodes] == ["95", "quoted parent", "O'Brien"]
    assert [node.edge_length for node in nodes] == [None, 0.02, -0.2]


@pytest.mark.parametrize("tree, length", [("A;", ""), ("A:9;", "9.0")])
def test_single_leaf_has_no_ancestors_and_zero_root_distance(inputs, tree, length):
    newick, mst_csv, output = inputs
    newick.write_text(tree, encoding="utf-8")

    assert build_evaluation_dataset(newick, mst_csv, output) == DatasetSummary(1, 1)
    (row,) = read_output(output)
    assert row["branch_length"] == length
    assert row["distance_from_root"] == "0"
    assert row["depth"] == "0"
    assert row["parent_label"] == row["nearest_named_ancestor"] == row["ancestor_labels"] == ""
    assert row["tree_newick"] == (f"A:{length};" if length else "A;")
    assert len(read_newick_path(row["tree_newick"])) == 1


def test_only_source_columns_are_required_with_utf8_bom(inputs):
    newick, mst_csv, output = inputs
    newick.write_text("\ufeff(A:0.1,B:0.2);", encoding="utf-8")
    mst_csv.write_text(
        "\ufeffSource_ID,Source_Family,Source_Genus,Source_Species\nA,Family,Genus,None\n",
        encoding="utf-8",
    )

    assert build_evaluation_dataset(newick, mst_csv, output) == DatasetSummary(2, 1)
    assert read_output(output)[0]["species"] == "None"


def test_taxonomy_newick_preserves_labels_without_csv_or_tree_distances(inputs):
    newick, mst_csv, output = inputs
    newick.write_text("'ID_1':99;", encoding="utf-8")
    taxonomy = ["Family, A", "Genus_A", "Species (A): O'Brien"]
    with mst_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER.strip().split(","))
        writer.writerows(
            [
                ["ID_1", *taxonomy, "external-1", "", "", "", "0.0001"],
                ["ID_1", *taxonomy, "external-2", "", "", "", "0.9"],
            ]
        )

    assert build_evaluation_dataset(newick, mst_csv, output) == DatasetSummary(1, 1)
    (row,) = read_output(output)
    nodes = read_newick_path(row["taxonomy_newick"])
    assert [node.label for node in nodes] == [*taxonomy, "ID_1"]
    assert all(node.edge_length is None for node in nodes)
    assert row["tree_newick"] == "'ID_1':99.0;"


@pytest.mark.parametrize("missing", ["", "None", "NULL", "NA", "n/a", "nan", "unknown", "-"])
def test_missing_taxonomy_keeps_unnamed_rank_nodes_and_original_values(inputs, missing):
    newick, mst_csv, output = inputs
    with mst_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(MST_COLUMNS)
        writer.writerow(["A", missing, missing, missing])

    build_evaluation_dataset(newick, mst_csv, output)

    (row,) = read_output(output)
    assert (row["family"], row["genus"], row["species"]) == (missing, missing, missing)
    nodes = read_newick_path(row["taxonomy_newick"])
    assert [node.label for node in nodes] == [None, None, None, "A"]
    assert all(node.edge_length is None for node in nodes)


@pytest.mark.parametrize(
    "target_fields",
    [
        ["", "", "", ""],
        ["A", "Conflicting family", "Conflicting genus", "Conflicting species"],
        ["B", "Other family", "Other genus", "Other species"],
    ],
)
def test_target_fields_are_ignored_even_when_blank_or_conflicting(inputs, target_fields):
    newick, mst_csv, output = inputs
    with mst_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER.strip().split(","))
        writer.writerow(["A", "Family", "Genus", "Species", *target_fields, "unused"])

    assert build_evaluation_dataset(newick, mst_csv, output) == DatasetSummary(2, 1)
    (row,) = read_output(output)
    assert row["leaf_id"] == "A"
    assert (row["family"], row["genus"], row["species"]) == ("Family", "Genus", "Species")


def test_matching_only_target_id_does_not_produce_a_dataset(inputs):
    newick, mst_csv, output = inputs
    newick.write_text("B:0.2;", encoding="utf-8")

    with pytest.raises(ValueError, match="No tree leaf IDs match Source_ID"):
        build_evaluation_dataset(newick, mst_csv, output)

    assert set(output.parent.iterdir()) == {newick, mst_csv}


@pytest.mark.parametrize(
    "tree, message",
    [
        ("", "Unexpected end of stream"),
        ("(A:1,B:2);(C:3,D:4);", "exactly one Newick tree"),
        ("(A:1,B:2)", "Unexpected end of stream"),
        ("(A:1,A:2);", "duplicate leaf ID"),
        ("(A:1,:2);", "leaf without an ID"),
        ("(A:1,B);", "missing branch length"),
        ("(A:1,(B:2));", "missing branch length"),
        ("(A:1,B:nan);", "non-finite branch length"),
        ("(A:1,B:inf);", "non-finite branch length"),
        ("(A:1,B:-inf);", "non-finite branch length"),
        ("(C:1,D:2);", "No tree leaf IDs match"),
        ("(A:1,C:2,C:3);", "duplicate leaf ID"),
    ],
)
def test_invalid_trees_leave_no_partial_output(inputs, tree, message):
    newick, mst_csv, output = inputs
    newick.write_text(tree, encoding="utf-8")

    with pytest.raises((ValueError, DataParseError), match=message):
        build_evaluation_dataset(newick, mst_csv, output)

    assert set(output.parent.iterdir()) == {newick, mst_csv}


@pytest.mark.parametrize(
    "content, message",
    [
        ("", "missing CSV header"),
        (HEADER, "no MST source records"),
        (HEADER.replace("Source_ID", "Other_ID"), "missing required columns: Source_ID"),
        (HEADER.replace("Distance", "Source_ID"), "duplicate CSV column names"),
        (HEADER + BASIC_EDGE.replace(",0.1", ""), "record width"),
        (HEADER + BASIC_EDGE.replace(",0.1", ",0.1,extra"), "record width"),
        (HEADER + BASIC_EDGE.replace("A,", " ,", 1), "empty Source_ID"),
        (HEADER + '"unterminated', "unexpected end of data"),
        (
            HEADER + BASIC_EDGE + "A,Changed,Genus,Species,B,Other family,Other genus,None,0.2\n",
            "conflicting source taxonomy for 'A'",
        ),
    ],
)
def test_invalid_mst_is_rejected_without_output(inputs, content, message):
    newick, mst_csv, output = inputs
    mst_csv.write_text(content, encoding="utf-8")

    with pytest.raises((ValueError, csv.Error), match=message):
        build_evaluation_dataset(newick, mst_csv, output)

    assert set(output.parent.iterdir()) == {newick, mst_csv}


@pytest.mark.parametrize("source_column", MST_COLUMNS)
def test_all_source_columns_are_required(inputs, source_column):
    newick, mst_csv, output = inputs
    fields = HEADER.strip().split(",")
    fields.remove(source_column)
    mst_csv.write_text(",".join(fields) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=f"missing required columns: {source_column}"):
        build_evaluation_dataset(newick, mst_csv, output)


@pytest.mark.parametrize("destination", ["newick", "mst_csv", "output"])
def test_existing_files_are_never_overwritten(inputs, destination):
    newick, mst_csv, output = inputs
    output.write_text("existing output", encoding="utf-8")
    paths = {"newick": newick, "mst_csv": mst_csv, "output": output}
    original = {path: path.read_bytes() for path in paths.values()}

    with pytest.raises(FileExistsError, match="already exists"):
        build_evaluation_dataset(newick, mst_csv, paths[destination])

    assert all(path.read_bytes() == content for path, content in original.items())


def test_concurrent_output_is_not_overwritten(inputs, monkeypatch):
    newick, mst_csv, output = inputs

    def competing_writer(source, destination):
        Path(destination).write_text("concurrent output", encoding="utf-8")
        raise FileExistsError("output appeared during processing")

    monkeypatch.setattr(evaluation_dataset.os, "link", competing_writer)
    with pytest.raises(FileExistsError, match="output appeared"):
        build_evaluation_dataset(newick, mst_csv, output)

    assert output.read_text(encoding="utf-8") == "concurrent output"
    assert set(output.parent.iterdir()) == {newick, mst_csv, output}


def test_cli_success_reports_matched_and_omitted_counts(inputs, capsys):
    newick, mst_csv, output = inputs
    newick.write_text("(A:0.1,B:0.2,C:0.3);", encoding="utf-8")

    assert main([str(newick), str(mst_csv), "-o", str(output)]) == 0

    captured = capsys.readouterr()
    assert "1 matched leaves of 3; omitted 2 unmatched leaves" in captured.out
    assert captured.err == ""
    assert len(read_output(output)) == 1


def test_cli_reports_invalid_newick_without_traceback(inputs, capsys):
    newick, mst_csv, output = inputs
    newick.write_text("(A:1,B:2)", encoding="utf-8")

    assert main([str(newick), str(mst_csv), "-o", str(output)]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error:")
    assert "Unexpected end of stream" in captured.err
    assert not output.exists()
