from __future__ import annotations

from pathlib import Path

from evospaice.tree import InputPaths, build_tree
from evospaice.viz import render_tree

REPOSITORY_ROOT = Path(__file__).parents[1]
MOCK_DATA = REPOSITORY_ROOT / "data" / "mock-tree"


def test_render_tree_creates_nonempty_png(tmp_path: Path) -> None:
    tree_result = build_tree(
        InputPaths(
            records=MOCK_DATA / "records.tsv",
            embeddings=MOCK_DATA / "embeddings.tsv",
            embedding_index=MOCK_DATA / "embedding-index.tsv",
            trust_policy=MOCK_DATA / "trust-policy.json",
            output_dir=tmp_path / "tree",
        )
    )

    image_path = render_tree(
        tree_result.tree_path,
        tmp_path / "tree.png",
        show_branch_lengths=True,
    )

    assert image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert image_path.stat().st_size > 10_000