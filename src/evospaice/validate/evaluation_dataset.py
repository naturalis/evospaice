"""Build a matched-leaf evaluation CSV from a Newick tree and MST source taxonomy."""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import dendropy
from dendropy.utility.error import DataParseError

TAXONOMY_COLUMNS = ("family", "genus", "species")
OUTPUT_COLUMNS = (
    "leaf_id",
    "branch_length",
    "distance_from_root",
    "depth",
    "parent_label",
    "nearest_named_ancestor",
    "ancestor_labels",
    *TAXONOMY_COLUMNS,
)
MST_COLUMNS = ("Source_ID", "Source_Family", "Source_Genus", "Source_Species")
Taxonomy = tuple[str, str, str]


@dataclass(frozen=True)
class DatasetSummary:
    total_leaves: int
    matched_leaves: int


def read_taxonomy(path: Path) -> dict[str, Taxonomy]:
    """Index Source_ID only, rejecting inconsistent source taxonomy for an ID."""
    taxonomy: dict[str, Taxonomy] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        columns = reader.fieldnames
        if not columns:
            raise ValueError(f"{path}: missing CSV header")
        if len(columns) != len(set(columns)):
            raise ValueError(f"{path}: duplicate CSV column names")
        missing = [column for column in MST_COLUMNS if column not in columns]
        if missing:
            raise ValueError(f"{path}: missing required columns: {', '.join(missing)}")
        for row in reader:
            location = f"{path}:{reader.line_num}"
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{location}: CSV record width does not match the header")
            identifier = row["Source_ID"]
            if not identifier.strip():
                raise ValueError(f"{location}: empty Source_ID")
            values = (row["Source_Family"], row["Source_Genus"], row["Source_Species"])
            previous = taxonomy.get(identifier)
            if previous is not None and previous != values:
                raise ValueError(
                    f"{location}: conflicting source taxonomy for {identifier!r}: "
                    f"{previous!r} versus {values!r}"
                )
            taxonomy[identifier] = values
    if not taxonomy:
        raise ValueError(f"{path}: no MST source records")
    return taxonomy


def iter_leaf_rows(path: Path) -> Iterator[dict[str, str]]:
    """Yield validated leaves in Newick order, without recursive traversal."""
    with path.open(encoding="utf-8-sig") as handle:
        trees = iter(
            dendropy.Tree.yield_from_files(
                [handle],
                schema="newick",
                preserve_underscores=True,
                suppress_leaf_node_taxa=True,
            )
        )
        tree = next(trees, None)
        if tree is None or next(trees, None) is not None:
            raise ValueError(f"{path}: expected exactly one Newick tree")

    seen: set[str] = set()
    stack: list[tuple[dendropy.Node, Decimal, int, tuple[str, ...]]] = [
        (tree.seed_node, Decimal(0), 0, ())
    ]
    while stack:
        node, distance, depth, ancestors = stack.pop()
        length = None
        if node.edge_length is None:
            if node.parent_node is not None:
                raise ValueError(f"{path}: missing branch length at node {node.label!r}")
        else:
            if not math.isfinite(node.edge_length):
                raise ValueError(f"{path}: non-finite branch length at node {node.label!r}")
            length = Decimal(str(node.edge_length))
            if node.parent_node is not None:
                distance += length

        if node.is_leaf():
            identifier = node.label
            if identifier is None or not identifier.strip():
                raise ValueError(f"{path}: leaf without an ID")
            if identifier in seen:
                raise ValueError(f"{path}: duplicate leaf ID {identifier!r}")
            seen.add(identifier)
            yield {
                "leaf_id": identifier,
                "branch_length": str(length) if length is not None else "",
                "distance_from_root": str(distance),
                "depth": str(depth),
                "parent_label": (node.parent_node.label or "") if node.parent_node else "",
                "nearest_named_ancestor": ancestors[-1] if ancestors else "",
                "ancestor_labels": " > ".join(ancestors),
            }
        else:
            lineage = ancestors + ((node.label,) if node.label else ())
            for child in reversed(node.child_nodes()):
                stack.append((child, distance, depth + 1, lineage))


def build_evaluation_dataset(newick: Path, mst_csv: Path, output: Path) -> DatasetSummary:
    """Write a matched-only CSV, refusing to overwrite any existing output."""
    if output.exists():
        raise FileExistsError(f"{output} already exists; choose a new output path")
    taxonomy = read_taxonomy(mst_csv)
    total = matched = 0
    temporary = tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=output.parent,
        prefix=f".{output.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with temporary as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for row in iter_leaf_rows(newick):
                total += 1
                values = taxonomy.get(row["leaf_id"])
                if values is not None:
                    row.update(zip(TAXONOMY_COLUMNS, values, strict=True))
                    writer.writerow(row)
                    matched += 1
            if not matched:
                raise ValueError("No tree leaf IDs match Source_ID")
        # Publish the complete file atomically, without replacing a concurrent output.
        os.link(temporary.name, output)
    finally:
        Path(temporary.name).unlink()
    return DatasetSummary(total_leaves=total, matched_leaves=matched)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("newick", type=Path, help="Newick tree with leaf IDs and branch lengths")
    parser.add_argument(
        "mst_csv",
        type=Path,
        help="MST CSV containing Source_ID and source taxonomy; Target_* ignored",
    )
    parser.add_argument(
        "-o", "--output", type=Path, required=True, help="New output CSV; must not already exist"
    )
    args = parser.parse_args(argv)
    try:
        summary = build_evaluation_dataset(args.newick, args.mst_csv, args.output)
    except (OSError, ValueError, csv.Error, DataParseError) as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    print(
        f"Created {args.output}: {summary.matched_leaves:,} matched leaves "
        f"of {summary.total_leaves:,}; "
        f"omitted {summary.total_leaves - summary.matched_leaves:,} unmatched leaves."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
