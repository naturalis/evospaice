"""Align two trees (or a tree and a metadata table) to a common tip set.

Used to align a sequence-based reference tree with an embeddings tree built
from a different record subset, so the two trees can be compared on
exactly the same tips.

Two modes, selected by which of --other-tree / --metadata is given:

* Tree-vs-tree: prune --tree and --other-tree down to the intersection of
  their tip labels, writing both pruned trees plus a report comparing them.
* Tree-vs-metadata: prune --tree down to the IDs listed in --metadata,
  writing the pruned tree plus a report noting any metadata IDs that were
  not found in the tree.

Run as a script, e.g.:
    python -m evospaice.validate.align_trees \\
        --tree reference.tre --other-tree embeddings.tre \\
        --output reference.pruned.tre --other-output embeddings.pruned.tre
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import dendropy


def read_ids(metadata_path: Path, id_column: str = "id") -> set[str]:
    """Read the distinct, non-empty values of `id_column` from a TSV file."""
    with open(metadata_path, newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if id_column not in (reader.fieldnames or []):
            raise ValueError(f"{metadata_path} has no '{id_column}' column")
        return {row[id_column] for row in reader if row[id_column]}


def tree_tip_labels(tree_path: Path) -> set[str]:
    """Return the set of leaf taxon labels in a Newick tree file."""
    tree = dendropy.Tree.get(path=str(tree_path), schema="newick")
    return {leaf.taxon.label for leaf in tree.leaf_node_iter()}


def prune_and_write(tree_path: Path, keep_ids: set[str], output_path: Path) -> None:
    """Prune `tree_path` down to tips in `keep_ids` and write it to `output_path`.

    Tips outside `keep_ids` are silently ignored (not every ID need appear
    in the tree), so this is safe to call with an ID set from another tree
    or from a metadata table.
    """
    tree = dendropy.Tree.get(path=str(tree_path), schema="newick")
    labels = {leaf.taxon.label for leaf in tree.leaf_node_iter()}
    tree.retain_taxa_with_labels(labels & keep_ids)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(path=str(output_path), schema="newick", suppress_rooting=True)


def _pct(part: int, whole: int) -> str:
    """Format `part` as a percentage of `whole`, or "n/a" if `whole` is 0."""
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def write_report(report_path: Path, sections: list[str]) -> None:
    """Write `sections` to `report_path`, one per line."""
    report_path.write_text("\n".join(sections) + "\n")


def _overlap_lines(name_a: str, count_a: int, name_b: str, count_b: int, overlap: int) -> list[str]:
    """Build the aligned "Tips in / Overlap / Dropped" block of a report."""
    return [
        f"Tips in {name_a}:{' ' * max(1, 34 - len(name_a))}{count_a}",
        f"Tips in {name_b}:{' ' * max(1, 34 - len(name_b))}{count_b}",
        f"Overlap (kept in both):{' ' * 20}{overlap} "
        f"({_pct(overlap, count_a)} of {name_a}, {_pct(overlap, count_b)} of {name_b})",
        f"Dropped from {name_a}:{' ' * max(1, 22 - len(name_a))}{count_a - overlap}",
        f"Dropped from {name_b}:{' ' * max(1, 22 - len(name_b))}{count_b - overlap}",
    ]


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser; see the module docstring for the two run modes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True, help="First tree to align (Newick).")
    parser.add_argument("--output", type=Path, required=True, help="Path to write the pruned --tree.")

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--other-tree", type=Path, help="Second tree to align against (Newick).")
    source.add_argument("--metadata", type=Path, help="TSV with an id column of tips to keep instead.")

    parser.add_argument("--id-column", default="id", help="Column in --metadata holding tip IDs (default: id).")
    parser.add_argument(
        "--other-output", type=Path, help="Path to write the pruned --other-tree (required with --other-tree)."
    )
    parser.add_argument("--report", type=Path, help="Path for the stats report (default: <output>_report.txt).")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: parse args, run the selected alignment mode, and report."""
    args = build_parser().parse_args(argv)
    if args.other_tree and not args.other_output:
        raise SystemExit("--other-output is required together with --other-tree")
    report_path = args.report or args.output.with_name(args.output.stem + "_report.txt")

    tree_a_labels = tree_tip_labels(args.tree)

    if args.other_tree:
        tree_b_labels = tree_tip_labels(args.other_tree)
        overlap = tree_a_labels & tree_b_labels
        prune_and_write(args.tree, overlap, args.output)
        prune_and_write(args.other_tree, overlap, args.other_output)

        sections = [
            "evospaice tree alignment report",
            "================================================",
            f"Tree A:          {args.tree}  ->  {args.output}",
            f"Tree B:          {args.other_tree}  ->  {args.other_output}",
            "",
            "Tip counts",
            "------------------------------------------------",
            *_overlap_lines("tree A", len(tree_a_labels), "tree B", len(tree_b_labels), len(overlap)),
        ]
        write_report(report_path, sections)
        print(f"wrote {args.output}, {args.other_output} and {report_path}", file=sys.stderr)
    else:
        keep_ids = read_ids(args.metadata, args.id_column)
        overlap = tree_a_labels & keep_ids
        prune_and_write(args.tree, keep_ids, args.output)

        sections = [
            "evospaice reference tree pruning report",
            "================================================",
            f"Input tree:      {args.tree}",
            f"Metadata file:   {args.metadata}",
            f"Output tree:     {args.output}",
            "",
            "Tip counts",
            "------------------------------------------------",
            *_overlap_lines("input tree", len(tree_a_labels), "metadata", len(keep_ids), len(overlap)),
        ]
        missing_from_tree = keep_ids - tree_a_labels
        if missing_from_tree:
            sections += ["", "Example metadata IDs missing from tree:",
                         *[f"  {i}" for i in sorted(missing_from_tree)[:10]]]
        write_report(report_path, sections)
        print(f"wrote {args.output} and {report_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
