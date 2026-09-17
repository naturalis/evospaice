"""Prune a tree down to one taxonomic group, at any rank.

A thin, dynamic layer over `alignment.py`'s tree-vs-metadata mode: instead
of handing it a pre-built ID list, give it a metadata TSV plus a rank
column and a value (e.g. `--rank genus --value Papilio`), and it derives
the ID list itself, writes it out for reuse, then prunes the tree exactly
the way `alignment.py --metadata` would.

Run as a script, e.g.:
    python -m evospaice.align_trees.taxon_subtree \\
        --tree overlap.tre --metadata taxonomy.tsv \\
        --rank genus --value Papilio \\
        --output papilio.tre
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from evospaice.align_trees.alignment import (
    _overlap_lines,
    prune_and_write,
    tree_tip_labels,
    write_report,
)


def read_ids_by_rank(metadata_path: Path, rank: str, value: str, id_column: str = "id") -> set[str]:
    """Return the `id_column` values of rows where `rank` equals `value`."""
    with open(metadata_path, newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = reader.fieldnames or []
        missing = {rank, id_column} - set(fields)
        if missing:
            raise ValueError(
                f"{metadata_path} has no column(s) {sorted(missing)}; available: {fields}"
            )
        return {row[id_column] for row in reader if row[rank] == value and row[id_column]}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser; see the module docstring for what this does."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True, help="Tree to prune (Newick).")
    parser.add_argument(
        "--metadata", type=Path, required=True,
        help="TSV with taxonomy columns, e.g. id/family/genus/species.",
    )
    parser.add_argument(
        "--rank", required=True,
        help="Metadata column to filter on, e.g. 'genus', 'family', 'species'.",
    )
    parser.add_argument("--value", required=True, help="Value to match in --rank, e.g. 'Papilio'.")
    parser.add_argument("--id-column", default="id", help="Metadata column holding tip IDs (default: id).")
    parser.add_argument("--output", type=Path, required=True, help="Path to write the pruned tree.")
    parser.add_argument(
        "--ids-output", type=Path,
        help="Path to write the matched ID list (default: <output>_ids.tsv). Reusable input for "
             "alignment.py --metadata, and useful for rerunning this exact subset later.",
    )
    parser.add_argument("--report", type=Path, help="Path for the stats report (default: <output>_report.txt).")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: filter metadata by rank/value, write the ID list, then prune."""
    args = build_parser().parse_args(argv)
    ids_output = args.ids_output or args.output.with_name(args.output.stem + "_ids.tsv")
    report_path = args.report or args.output.with_name(args.output.stem + "_report.txt")

    keep_ids = read_ids_by_rank(args.metadata, args.rank, args.value, args.id_column)
    if not keep_ids:
        raise SystemExit(f"No rows in {args.metadata} have {args.rank}={args.value!r}")

    ids_output.parent.mkdir(parents=True, exist_ok=True)
    ids_output.write_text(args.id_column + "\n" + "\n".join(sorted(keep_ids)) + "\n")

    tree_labels = tree_tip_labels(args.tree)
    overlap = tree_labels & keep_ids
    prune_and_write(args.tree, keep_ids, args.output)

    sections = [
        "evospaice taxon subtree report",
        "================================================",
        f"Input tree:      {args.tree}",
        f"Metadata file:   {args.metadata}",
        f"Filter:          {args.rank} == {args.value!r}",
        f"ID list:         {ids_output}",
        f"Output tree:     {args.output}",
        "",
        "Tip counts",
        "------------------------------------------------",
        *_overlap_lines("input tree", len(tree_labels), f"{args.rank}={args.value}", len(keep_ids), len(overlap)),
    ]
    missing_from_tree = keep_ids - tree_labels
    if missing_from_tree:
        sections += ["", f"Example {args.value} IDs missing from tree:",
                     *[f"  {i}" for i in sorted(missing_from_tree)[:10]]]
    write_report(report_path, sections)
    print(f"wrote {ids_output}, {args.output} and {report_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
