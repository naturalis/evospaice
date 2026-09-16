"""Compare trees using RF and tip-to-root correlation by default."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zlib
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from time import monotonic

from dendropy.utility.error import DataParseError

from .compare import (
    align_taxa,
    leaf_labels,
    load_tree,
    prepare_trees,
    root_to_node_lengths,
    tip_to_root_correlation,
    topology_metrics,
)


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
    parser.add_argument("--rf", action=argparse.BooleanOptionalAction, default=True,
                        help="Compute RF topology distance (default: enabled)")
    parser.add_argument("--tip-to-root-correlation", action=argparse.BooleanOptionalAction,
                        default=True,
                        help="Correlate tip lengths from supplied roots (default: enabled)")
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


def _serialize_csv(rows: list[dict], fields: list[str]) -> str:
    with io.StringIO(newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return handle.getvalue()


def run(args: argparse.Namespace) -> int:
    """Validate and serialize all scores and provenance before writing outputs."""
    started = monotonic()

    def progress(percent: int, message: str) -> None:
        print(f"[{percent:3d}%] [{monotonic() - started:.1f}s] {message}",
              file=sys.stderr, flush=True)

    progress(0, "Starting validation (percentages track stages, not elapsed time); checking inputs")
    if not args.rf and not args.tip_to_root_correlation:
        raise ValueError("At least one metric must be enabled")
    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
        raise ValueError("Output directory is not empty; select a new directory or --overwrite")
    input_paths = [
        path for name in ("inferred", "reference", "taxon_map", "taxa_file", "metadata")
        if (path := getattr(args, name)) is not None
    ]
    filenames = ["taxa.csv", "validation.json"]
    if args.rf:
        filenames.append("clades.csv")
    if args.tip_to_root_correlation:
        filenames.extend(["node_lengths.csv", "tip_to_root_correlation.csv"])
    for filename in filenames:
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
    originals = {}
    for index, (name, path) in enumerate(inputs.items(), start=1):
        progress(index * 10, f"Loading {name} tree: {path}")
        originals[name] = load_tree(path)
        progress(index * 10, f"Loaded {name} tree: {len(leaf_labels(originals[name])):,} tips")
    mappings = _mappings(args.taxon_map)
    trees = {}
    if args.rf:
        progress(30, f"Aligning taxa ({args.taxa_policy}, {args.mode}); "
                 "cloning, pruning and indexing trees may take time")
        trees, coverage = prepare_trees(
            originals, mode=args.mode, taxa_policy=args.taxa_policy, mappings=mappings,
            selected=selected,
        )
        taxa = leaf_labels(trees["inferred"])
    else:
        progress(30, f"Matching taxon labels ({args.taxa_policy}); "
                 "skipping topology preparation (--no-rf)")
        taxa, coverage = align_taxa(
            originals, mode=args.mode, taxa_policy=args.taxa_policy, mappings=mappings,
            selected=selected, require_rf=False,
        )
    progress(40, f"Alignment complete: {len(taxa):,} shared tips retained, "
             f"{sum(not row['retained'] for row in coverage):,} tips excluded across both trees; "
             + ("computing RF topology distance" if args.rf else "RF disabled (--no-rf)"))
    topology, clades = None, []
    if args.rf:
        topology, clades = topology_metrics(trees["inferred"], trees["reference"])
    progress(50, "Topology stage complete; "
             + ("measuring original-root branch lengths" if args.tip_to_root_correlation
                else "tip-to-root correlation disabled"))
    length_metric, node_rows, tip_rows = None, [], []
    if args.tip_to_root_correlation:
        units = metadata.get("branch_length_units", {})
        if not isinstance(units, dict):
            raise ValueError("Metadata branch_length_units must be a JSON object")
        branch_length_units = {name: units.get(name, "unknown") for name in originals}
        if any(
            not isinstance(unit, str) or not unit.strip()
            for unit in branch_length_units.values()
        ):
            raise ValueError("Metadata branch_length_units values must be nonempty strings")
        retained_lengths = {}
        for index, (name, original) in enumerate(originals.items()):
            progress(50 + index * 10, f"Measuring {name} root-to-node lengths")
            rows, tip_lengths = root_to_node_lengths(original, name=name)
            node_rows.extend(rows)
            retained_lengths[name] = [
                (row["taxon"], tip_lengths[row["label"]]) for row in coverage
                if row["tree"] == name and row["retained"]
            ]
            progress(60 + index * 10, f"Measured {name}: {len(rows):,} nodes, "
                     f"{len(retained_lengths[name]):,} retained tips")
        progress(70, f"Computing Spearman tip-to-root correlation for {len(taxa):,} matched tips")
        length_metric, tip_rows = tip_to_root_correlation(
            retained_lengths["reference"], retained_lengths["inferred"], retained_taxa=taxa,
        )
        length_metric.update(
            root_policy="original_supplied_root_stem_excluded",
            branch_lengths="stored_non_root_edges",
            branch_length_units=branch_length_units,
            node_id_policy="tree_local_preorder_indices",
        )
    else:
        progress(60, "Skipping root-to-node lengths (tip-to-root correlation disabled)")
        progress(70, "Skipping Spearman tip-to-root correlation")
    progress(80, "Metrics complete; hashing inputs and collecting provenance")
    warnings = []
    if length_metric is not None:
        warnings.append(
            "tip-to-root-correlation uses the original supplied roots; matching tips "
            "does not establish comparable roots. Raw sums may have different units."
        )
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
    progress(90, "Input hashes complete; serializing JSON and CSV reports")
    report: dict = dict(
        schema_version=5, reference_kind=args.reference_kind,
        reference_independence=args.reference_independence, metadata=metadata, warnings=warnings,
        branch_lengths="ignored", taxa_policy=args.taxa_policy, retained_taxa=len(taxa),
        coverage={name: dict(original=sum(row["tree"] == name for row in coverage),
                             retained=len(taxa)) for name in originals},
        versions={"dendropy": version("dendropy")},
        inputs=input_identities,
    )
    outputs = {
        "taxa.csv": _serialize_csv(coverage, ["tree", "label", "taxon", "retained", "reason"]),
    }
    if topology is not None:
        report.update(topology=topology, mode=args.mode,
                      root_policy="supplied_root" if args.mode == "rooted" else "unrooted_splits")
        outputs["clades.csv"] = _serialize_csv(clades, ["clade_id", "origin", "size"])
    if length_metric is not None:
        report["tip_to_root_correlation"] = length_metric
        report["branch_lengths"] = dict(tip_to_root_correlation="used")
        if args.rf:
            report["branch_lengths"]["rf"] = "ignored"
        report["versions"]["scipy"] = version("scipy")
        outputs["node_lengths.csv"] = _serialize_csv(
            node_rows, ["tree", "node_id", "parent_id", "original_label", "node_kind",
                        "root_to_node_sum"],
        )
        outputs["tip_to_root_correlation.csv"] = _serialize_csv(
            tip_rows, ["taxon", "reference_sum", "inferred_sum", "reference_rank", "inferred_rank"],
        )
    outputs["validation.json"] = json.dumps(report, indent=2, allow_nan=False) + "\n"
    progress(95, f"Writing {len(outputs)} report files to {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in outputs.items():
        (args.output_dir / filename).write_text(content, encoding="utf-8", newline="")
    if topology is not None:
        print(json.dumps(topology, indent=2, allow_nan=False))
    if length_metric is not None:
        score = length_metric["rho"]
        if score is None:
            score = f"undefined ({length_metric['undefined_reason']})"
        print(f"tip-to-root-correlation: {score}")
    progress(100, f"Validation complete; reports saved to {args.output_dir}")
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
        print("Validation interrupted by user", file=sys.stderr, flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())