"""Compare inferred and reference tree topology using RF, precision and recall."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import zlib
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from dendropy.utility.error import DataParseError

from .compare import leaf_labels, load_tree, prepare_trees, topology_metrics


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inferred", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--mode", choices=["rooted", "unrooted"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--taxa-policy", choices=["strict", "intersection"], default="strict")
    parser.add_argument("--taxon-map", type=Path)
    parser.add_argument("--taxa-file", type=Path)
    parser.add_argument("--reference-kind", choices=["phylogeny", "taxonomy"], default="phylogeny")
    parser.add_argument("--reference-independence", choices=["independent", "backbone-derived",
                                                          "unknown"], default="unknown")
    parser.add_argument("--metadata", type=Path, help="JSON citations and provenance")
    parser.add_argument("--max-tips", type=int, default=5000)
    return parser


def read_table(path: Path, required: set[str]) -> list[dict[str, str]]:
    """Read a bounded TSV with named columns, rejecting ragged or empty rows."""
    if path.stat().st_size > 32 * 1024**2:
        raise ValueError("Table exceeds 32 MiB benchmark input limit")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = reader.fieldnames or []
        if not required <= set(fields) or len(fields) != len(set(fields)):
            raise ValueError(f"Table requires unique columns including {sorted(required)}")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Ragged table row")
            if any(not row[key].strip() for key in required):
                raise ValueError("Missing required table value")
            rows.append(row)
    if not rows:
        raise ValueError("Table contains no data rows")
    return rows


def _mappings(path: Path | None) -> dict:
    result = {"inferred": {}, "reference": {}}
    if path is not None:
        for row in read_table(path, {"tree", "label", "taxon"}):
            name, label, taxon = row["tree"], row["label"], row["taxon"]
            if name not in result or label in result[name]:
                raise ValueError("Taxon map has invalid tree names or duplicate labels")
            result[name][label] = taxon
    return result


def _input_identity(path: Path) -> dict:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return dict(path=str(path), sha256=digest)


def _csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    """Write topology scores, taxon coverage and input provenance."""
    if args.max_tips < 1:
        raise ValueError("max_tips must be positive")
    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
        raise ValueError("Output directory is not empty; select a new directory or --overwrite")
    input_paths = [
        path for name in ("inferred", "reference", "taxon_map", "taxa_file", "metadata")
        if (path := getattr(args, name)) is not None
    ]
    for filename in ("taxa.csv", "clades.csv", "validation.json"):
        output = args.output_dir / filename
        for source in input_paths:
            if output.resolve() == source.resolve() or (
                output.exists() and output.samefile(source)
            ):
                raise ValueError(f"Output would overwrite an input file: {source}")
    metadata = json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else {}
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be a JSON object")
    json.dumps(metadata, allow_nan=False)
    selected = None
    if args.taxa_file:
        selected = {row["taxon"] for row in read_table(args.taxa_file, {"taxon"})}
    inputs = {"inferred": args.inferred, "reference": args.reference}
    trees, coverage = prepare_trees(
        {name: load_tree(path, max_tips=args.max_tips) for name, path in inputs.items()},
        mode=args.mode, taxa_policy=args.taxa_policy, mappings=_mappings(args.taxon_map),
        selected=selected, max_tips=args.max_tips,
    )
    taxa = leaf_labels(trees["inferred"])
    topology, clades = topology_metrics(trees["inferred"], trees["reference"])
    warnings = []
    if args.reference_kind == "taxonomy":
        warnings.append(
            "Taxonomy reference: structural consistency, not independent phylogenetic accuracy"
        )
    if args.reference_independence != "independent":
        warnings.append("Reference independence is not established; circular evaluation may apply")
    else:
        warnings.append(
            "Reference independence is declared by the caller, not verified automatically"
        )
    input_identities = {name: _input_identity(path) for name, path in inputs.items()}
    for name in ("taxon_map", "taxa_file", "metadata"):
        if path := getattr(args, name):
            input_identities[name] = _input_identity(path)
    report = dict(
        schema_version=2, mode=args.mode, reference_kind=args.reference_kind,
        reference_independence=args.reference_independence, metadata=metadata, warnings=warnings,
        root_policy="supplied_root" if args.mode == "rooted" else "unrooted_splits",
        branch_lengths="ignored", taxa_policy=args.taxa_policy, retained_taxa=len(taxa),
        coverage={name: dict(original=sum(row["tree"] == name for row in coverage),
                             retained=len(taxa)) for name in trees},
        topology=topology, limits=dict(max_tips=args.max_tips),
        versions={"dendropy": version("dendropy")},
        inputs=input_identities,
    )
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _csv(args.output_dir / "taxa.csv", coverage, ["tree", "label", "taxon", "retained", "reason"])
    _csv(args.output_dir / "clades.csv", clades, ["clade_id", "origin", "size"])
    (args.output_dir / "validation.json").write_text(serialized, encoding="utf-8")
    print(json.dumps(topology, indent=2, allow_nan=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, DataParseError) as error:
        parser.error(str(error))
    except (OSError, EOFError, zlib.error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())