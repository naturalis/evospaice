"""Extract a named clade and a species-labelled display copy for Taxonium."""

from __future__ import annotations

import argparse
import copy
import csv
from pathlib import Path

from Bio import Phylo
from Bio.Phylo.BaseTree import Tree


def extract(tree_path: Path, metadata_path: Path, clade_name: str, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"{output} already exists; choose a new output directory")
    tree = Phylo.read(tree_path, "newick")
    matches = [clade for clade in tree.find_clades() if clade.name == clade_name]
    if len(matches) != 1:
        raise ValueError(f"Expected one {clade_name!r} clade, found {len(matches)}")
    with metadata_path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not {"id", "species"} <= set(reader.fieldnames or ()):
            raise ValueError("Metadata must contain id and species columns")
        species = {}
        for row in reader:
            if row["id"] in species:
                raise ValueError(f"Duplicate metadata ID: {row['id']}")
            species[row["id"]] = row["species"]
    clade = copy.deepcopy(matches[0])
    clade.branch_length = 0.0
    subtree = Tree(root=clade, rooted=True)
    leaves = subtree.get_terminals()
    if any(leaf.name not in species for leaf in leaves):
        raise ValueError("A clade leaf is missing from the species metadata")
    output.mkdir(parents=True)
    Phylo.write(subtree, output / "original-ids.nwk", "newick", format_branch_length="%1.12g")
    for leaf in leaves:
        leaf.name = f"{species[leaf.name]} | {leaf.name}"
    Phylo.write(subtree, output / "species-labels.nwk", "newick", format_branch_length="%1.12g")
    return {
        "clade": clade_name,
        "records": len(leaves),
        "species": len({species[leaf.name] for leaf in matches[0].get_terminals()}),
        "display_tree": str(output / "species-labels.nwk"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--clade", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(extract(args.tree, args.metadata, args.clade, args.output_dir))


if __name__ == "__main__":
    main()
