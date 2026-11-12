"""Build a taxonomy-only baseline tree for a set of tips.

The baseline has the same tips as the inferred trees but no information from
sequences or embeddings: tips hang in polytomies under their species, nested in
genus, tribe, subfamily and family nodes looked up in the BOLD taxonomy
scaffold. Scoring this tree with ``evaluate.py`` against the reference shows how
much topological agreement the taxonomic constraint alone already provides, so
that RF values for embedding-derived trees can be read against it.

Usage (from the repository root)::

    python -m evospaice.validate.taxonomy_baseline \
        --taxonomy data/pruned.taxonomy.tsv \
        --scaffold data/BOLD_Public.30-Jun-2026.tre.gz \
        --reference data/pruned.tre.txt \
        --out results/taxonomy_baseline.tre
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from evospaice.validate.rank_stratified import PatristicTree, species_lineages

RANKS = ["family", "subfamily", "tribe", "genus", "species"]


def quote(label: str) -> str:
    return "'" + label.replace("'", "''") + "'"


def build(tips: dict[str, str], lineages: dict[str, dict[str, str]]) -> str:
    tree: dict = {}
    for tip, sp in sorted(tips.items()):
        lin = lineages.get(sp, {})
        path = []
        for rank in RANKS:
            name = sp if rank == "species" else lin.get(rank)
            if rank == "genus" and not name:
                name = sp.split()[0]
            if name:
                path.append(f"{rank}:{name}")
        node = tree
        for step in path:
            node = node.setdefault(step, {})
        node.setdefault("__tips__", []).append(tip)

    def emit(name: str, node: dict) -> str:
        parts = [emit(k, v) for k, v in sorted(node.items()) if k != "__tips__"]
        parts += [quote(t) for t in node.get("__tips__", [])]
        if len(parts) == 1 and not node.get("__tips__") is None and name:
            return parts[0]
        return "(" + ",".join(parts) + ")" + (quote(name) if name else "")

    return emit("", tree) + ";\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--taxonomy", type=Path, required=True)
    ap.add_argument("--scaffold", type=Path, required=True)
    ap.add_argument("--reference", type=Path, required=True,
                    help="only tips present in this tree are kept")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    ref = PatristicTree(args.reference)
    with open(args.taxonomy) as fh:
        tips = {r["node"]: r["species"] for r in csv.DictReader(fh, delimiter="\t")
                if r["node"] in ref.tip}
    lineages = species_lineages(args.scaffold)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(tips, lineages))
    print(f"wrote {args.out} with {len(tips)} tips")


if __name__ == "__main__":
    main()
