"""Tests for taxonomy metadata extraction from Newick trees."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

from evospaice.ingest.taxonomy_metadata import (
    NewickParser,
    iter_species_metadata,
    write_species_metadata,
)


def test_uses_nearest_quoted_ancestor_as_species() -> None:
    tree = NewickParser(
        "(((PROCESS1:0.1)'Genus_species':0.2):0.3,PROCESS2:0.4)Family:0.5;"
    ).parse()

    assert list(iter_species_metadata(tree)) == [("PROCESS1", "Genus species")]


def test_preserves_escaped_quotes_and_skips_comments() -> None:
    tree = NewickParser("(ID1[&flag=yes]:1)'Genus_o''species':0;").parse()

    assert list(iter_species_metadata(tree)) == [("ID1", "Genus o'species")]


def test_writes_taxonium_tsv(tmp_path: Path) -> None:
    source = tmp_path / "taxonomy.tre.txt"
    source.write_text("((ID1:0)'Species_one':0,(ID2:0)'Species_two':0)Genus:0;", encoding="utf-8")
    output = StringIO()

    count = write_species_metadata(source, output)

    assert count == 2
    assert output.getvalue() == "node\tspecies\nID1\tSpecies one\nID2\tSpecies two\n"