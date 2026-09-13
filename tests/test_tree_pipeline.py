from __future__ import annotations

import csv
import json
from pathlib import Path

from evospaice.cli import main
from evospaice.tree import InputPaths, TreeBuildConfig, build_tree


REPOSITORY_ROOT = Path(__file__).parents[1]
MOCK_DATA = REPOSITORY_ROOT / "data" / "mock-tree"
LEAF_IDS = {f"BOLD:MOCK{index:03d}" for index in range(1, 7)}


def mock_paths(output_dir: Path) -> InputPaths:
    return InputPaths(
        records=MOCK_DATA / "records.tsv",
        embeddings=MOCK_DATA / "embeddings.tsv",
        embedding_index=MOCK_DATA / "embedding-index.tsv",
        trust_policy=MOCK_DATA / "trust-policy.json",
        output_dir=output_dir,
    )


def test_build_tree_writes_complete_reproducible_artifacts(tmp_path: Path) -> None:
    result = build_tree(mock_paths(tmp_path), TreeBuildConfig(max_nj_children=8))

    assert result.leaf_count == 6
    assert result.tree_path.exists()
    assert result.diagnostics_path.exists()
    assert result.exclusions_path.exists()
    assert result.manifest_path.exists()
    assert (tmp_path / "checkpoints" / "complete.json").exists()

    newick = result.tree_path.read_text(encoding="utf-8")
    assert newick.endswith(";\n")
    for leaf_id in LEAF_IDS:
        assert newick.count(f"'{leaf_id}'") == 1

    with result.diagnostics_path.open(encoding="utf-8", newline="") as handle:
        diagnostics = list(csv.DictReader(handle, delimiter="\t"))
    assert any(row["topology_method"] == "neighbor_joining" for row in diagnostics)
    assert max(int(row["child_count"]) for row in diagnostics) == 4
    assert max(int(row["distance_matrix_size"]) for row in diagnostics) == 16

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "complete"
    assert manifest["policy_version"] == "mock-v1"
    assert manifest["distance_scope"]["global_matrix_created"] is False
    assert manifest["distance_scope"]["largest_local_matrix_elements"] == 16


def test_tree_cli_runs_the_mock_dataset(tmp_path: Path, capsys) -> None:
    exit_code = main(
        [
            "tree",
            "--records",
            str(MOCK_DATA / "records.tsv"),
            "--embeddings",
            str(MOCK_DATA / "embeddings.tsv"),
            "--embedding-index",
            str(MOCK_DATA / "embedding-index.tsv"),
            "--trust-policy",
            str(MOCK_DATA / "trust-policy.json"),
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert str(tmp_path / "scaled-tree.nwk") in capsys.readouterr().out
