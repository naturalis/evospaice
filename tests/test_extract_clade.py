from pathlib import Path

import pytest
from Bio import Phylo

from evospaice.viz.taxonium.extract_clade import extract


def test_extract_preserves_internal_paths_and_original_ids(tmp_path: Path) -> None:
    source = tmp_path / "source.nwk"
    source.write_text("((a:1,b:2)'genus:Papilio':7,c:3)root;")
    metadata = tmp_path / "metadata.tsv"
    metadata.write_text("id\tspecies\na\tPapilio one\nb\tPapilio two\nc\tOther species\n")
    output = tmp_path / "papilio"
    report = extract(source, metadata, "genus:Papilio", output)
    assert report["records"] == report["species"] == 2
    tree = Phylo.read(output / "original-ids.nwk", "newick")
    assert tree.distance("a", "b") == 3
    assert tree.root.branch_length == 0
    display = Phylo.read(output / "species-labels.nwk", "newick")
    assert {leaf.name for leaf in display.get_terminals()} == {
        "Papilio one | a", "Papilio two | b",
    }
    assert Phylo.read(source, "newick").distance("a", "b") == 3
    with pytest.raises(FileExistsError):
        extract(source, metadata, "genus:Papilio", output)


def test_missing_named_clade_is_an_error(tmp_path: Path) -> None:
    source = tmp_path / "source.nwk"
    source.write_text("(a:1,b:2)root;")
    with pytest.raises(ValueError, match="found 0"):
        extract(source, tmp_path / "unused.tsv", "genus:Papilio", tmp_path / "output")
