"""Evaluate inferred trees against a reference and optional embedding benchmarks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import random
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

from dendropy.utility.error import DataParseError

from evospaice.diversity.evaluate import load_samples
from evospaice.diversity.metrics import Backend, faith_pd, unweighted_unifrac, weighted_unifrac

from .compare import (
    branch_metrics,
    branch_qc,
    distance_summary,
    leaf_labels,
    load_tree,
    prepare_trees,
    sample_pairs,
    support_view,
    topology_metrics,
)
from .diagnostics import (
    embedding_diagnostics,
    load_distances,
    load_taxonomy,
    load_vectors,
    read_table,
    replicate_support,
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
    parser.add_argument("--length-mode", choices=["none", "raw", "total-length"], default="none")
    parser.add_argument("--inferred-units")
    parser.add_argument("--reference-units")
    parser.add_argument("--baseline-units")
    parser.add_argument("--units-evidence", help="Provenance supporting compatible raw units")
    parser.add_argument("--max-tips", type=int, default=5000)
    parser.add_argument("--max-pairs", type=int, default=50_000)
    parser.add_argument("--max-quartets", type=int, default=10_000)
    parser.add_argument("--max-replicates", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--distances", type=Path)
    inputs.add_argument("--embedding-vectors", type=Path)
    parser.add_argument("--taxa-metadata", type=Path)
    parser.add_argument("--embedding-units", help="Required with --embedding-fit")
    parser.add_argument("--embedding-fit", action="store_true", help="Measure embedding path fit")
    parser.add_argument("--near-zero-distance", type=float)
    parser.add_argument("--baseline-tree", type=Path)
    parser.add_argument("--replicates", type=Path)
    parser.add_argument("--replicate-kind", choices=["bootstrap", "perturbation", "other"])
    parser.add_argument("--replicate-method")
    parser.add_argument("--support-field", help="Annotation key or 'label' for numeric node labels")
    parser.add_argument("--support-scale", choices=["fraction", "percent"])
    parser.add_argument("--min-reference-support", type=float, help="Topology cutoff in [0, 1]")
    parser.add_argument("--samples", type=Path)
    parser.add_argument(
        "--sample-taxa-policy", choices=["strict", "intersection"], default="strict"
    )
    parser.add_argument("--backend", choices=["skbio", "unifrac"], default="skbio")
    return parser


def diversity_sensitivity(
    inferred, reference, samples, *, length_mode="none", taxa_policy="strict",
    backend: Backend = "skbio",
    max_pairs=50_000,
) -> tuple[dict, list[dict], list[dict]]:
    """Compare sample scores on fixed study roots, exposing dropped sample mass."""
    if not inferred.is_rooted or not reference.is_rooted:
        raise ValueError("Diversity sensitivity requires --mode rooted with compatible study roots")
    if not branch_qc(inferred)["valid"] or not branch_qc(reference)["valid"]:
        return dict(status="not_evaluated", reason="invalid_or_missing_lengths"), [], []
    if len(samples) * (len(samples) - 1) // 2 > max_pairs:
        raise ValueError("Sample-pair limit exceeded; provide fewer samples or raise --max-pairs")
    trees = [inferred.clone(depth=2), reference.clone(depth=2)]
    if length_mode == "total-length":
        for tree in trees:
            total = branch_qc(tree)["total"]
            if total <= 0:
                return dict(status="not_evaluated", reason="zero_total_length"), [], []
            for node in tree.preorder_node_iter():
                node.edge_length /= total
    taxa = leaf_labels(inferred)
    filtered, alpha, beta = {}, [], []
    for sample, abundances in sorted(samples.items()):
        if any(not math.isfinite(value) or value < 0 for value in abundances.values()):
            raise ValueError("Sample abundances must be finite and non-negative")
        if taxa_policy == "strict" and abundances.keys() - taxa:
            raise ValueError(f"Sample {sample!r} contains taxa outside the compared trees")
        retained = {taxon: value for taxon, value in abundances.items() if taxon in taxa}
        filtered[sample] = retained
        total, kept = sum(abundances.values()), sum(retained.values())
        if not math.isfinite(total):
            raise ValueError("Sample total must be finite")
        richness = sum(value > 0 for value in abundances.values())
        values = [faith_pd(tree, retained) for tree in trees]
        row = dict(sample=sample, inferred_pd=values[0], reference_pd=values[1],
                   retained_abundance_fraction=kept / total if total else None,
                   retained_richness_fraction=(sum(value > 0 for value in retained.values())
                                               / richness) if richness else None)
        if length_mode != "none":
            row.update(pd_delta=values[0] - values[1], pd_relative_error=(values[0] - values[1]) / (
                values[1]
            ) if values[1] else None)
        alpha.append(row)
    for first, second in itertools.combinations(sorted(filtered), 2):
        row = dict(sample_a=first, sample_b=second)
        for label, function in (("unweighted_unifrac", unweighted_unifrac),
                                ("weighted_unifrac", weighted_unifrac)):
            values = []
            for tree in trees:
                try:
                    values.append(function(
                        tree, filtered[first], filtered[second], backend=backend
                    ))
                except ValueError as error:
                    if "undefined" not in str(error) and "sample total" not in str(error):
                        raise
                    values.append(None)
                    row[f"{label}_reason"] = str(error)
            row.update({f"inferred_{label}": values[0], f"reference_{label}": values[1],
                        f"{label}_delta": values[0] - values[1] if None not in values else None})
        beta.append(row)
    summaries = dict(status="evaluated", length_mode=length_mode, sample_taxa_policy=taxa_policy,
                     pd=distance_summary([row["inferred_pd"] for row in alpha],
                                         [row["reference_pd"] for row in alpha],
                                         errors=length_mode != "none"))
    for label in ("unweighted_unifrac", "weighted_unifrac"):
        valid = [row for row in beta if row[f"{label}_delta"] is not None]
        summaries[label] = distance_summary(
            [row[f"inferred_{label}"] for row in valid],
            [row[f"reference_{label}"] for row in valid], errors=True,
        )
    return summaries, alpha, beta


def _mappings(path: Path | None) -> dict:
    result = {"inferred": {}, "reference": {}, "baseline": {}}
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
    fieldnames = list(dict.fromkeys(fields + sorted({key for row in rows for key in row})))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    """Produce a report without claiming unavailable metrics or circular validation passed."""
    for name in ("max_tips", "max_pairs", "max_quartets", "max_replicates"):
        if getattr(args, name) < 1:
            raise ValueError(f"{name} must be positive")
    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.overwrite:
        raise ValueError("Output directory is not empty; select a new directory or --overwrite")
    if args.replicates and (not args.replicate_kind or not args.replicate_method):
        raise ValueError("--replicates requires --replicate-kind and --replicate-method")
    if bool(args.support_field) != bool(args.support_scale):
        raise ValueError("--support-field and --support-scale must be supplied together")
    if args.min_reference_support is not None and not args.support_field:
        raise ValueError("Reference support filtering requires --support-field and --support-scale")
    if args.near_zero_distance is not None and (
        not math.isfinite(args.near_zero_distance) or args.near_zero_distance < 0
    ):
        raise ValueError("--near-zero-distance must be finite and non-negative")
    if args.embedding_fit and (
        not args.embedding_units or args.embedding_units != args.inferred_units
    ):
        raise ValueError("--embedding-fit requires matching embedding and inferred distance units")
    if args.embedding_fit and not (args.distances or args.embedding_vectors):
        raise ValueError("--embedding-fit requires distances or vectors")
    if args.embedding_vectors and args.embedding_units not in {None, "cosine"}:
        raise ValueError("Vector diagnostics require --embedding-units cosine")
    metadata = json.loads(args.metadata.read_text(encoding="utf-8")) if args.metadata else {}
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be a JSON object")
    json.dumps(metadata, allow_nan=False)
    selected = None
    if args.taxa_file:
        selected = {row["taxon"] for row in read_table(args.taxa_file, {"taxon"})}
    mappings = _mappings(args.taxon_map)
    inputs = {"inferred": args.inferred, "reference": args.reference}
    if args.baseline_tree:
        inputs["baseline"] = args.baseline_tree
    trees, coverage, qc = prepare_trees(
        {name: load_tree(path, max_tips=args.max_tips) for name, path in inputs.items()},
        mode=args.mode,
        taxa_policy=args.taxa_policy, mappings=mappings, selected=selected, max_tips=args.max_tips,
    )
    inferred, reference = trees["inferred"], trees["reference"]
    taxa = leaf_labels(inferred)
    pairs = sample_pairs(sorted(taxa), args.max_pairs, args.seed)
    distances = load_distances(args.distances, taxa) if args.distances else None
    if distances is not None:
        candidates = sorted(distances)
        pairs = candidates if len(candidates) <= args.max_pairs else sorted(
            random.Random(args.seed).sample(candidates, args.max_pairs)
        )
    topology_reference, support_values, collapsed = reference, {}, 0
    if args.support_field:
        topology_reference, support_values, collapsed = support_view(
            reference, field=args.support_field, scale=args.support_scale,
            minimum=args.min_reference_support,
        )
    topology, clades = topology_metrics(inferred, topology_reference)
    for row in clades:
        row["reference_support"] = support_values.get(row["clade_id"])
    branches, pair_rows = branch_metrics(
        inferred, reference, pairs, length_mode=args.length_mode,
        inferred_units=args.inferred_units, reference_units=args.reference_units,
        units_evidence=args.units_evidence,
        original_qc={name: qc[name] for name in ("inferred", "reference")},
    )
    warnings = []
    if args.reference_kind == "taxonomy":
        warnings.append(
            "Taxonomy reference: structural consistency, not independent phylogenetic accuracy"
        )
    if args.reference_independence != "independent":
        warnings.append("Reference independence is not established; circular evaluation may apply")
    if args.reference_independence == "independent":
        warnings.append(
            "Reference independence is declared by the caller, not verified automatically"
        )
    report: dict[str, Any] = dict(
        schema_version=1, mode=args.mode, reference_kind=args.reference_kind,
        reference_independence=args.reference_independence, metadata=metadata, warnings=warnings,
        root_policy="supplied_study_root_excluding_incoming_stem" if args.mode == "rooted"
        else "unrooted_splits_degree_two_seed_suppressed",
        taxa_policy=args.taxa_policy, retained_taxa=len(taxa),
        coverage={name: dict(original=sum(row["tree"] == name for row in coverage),
                             retained=len(taxa)) for name in trees},
        topology=topology, branches=branches,
        support_filter=dict(field=args.support_field, scale=args.support_scale,
                    minimum=args.min_reference_support, collapsed=collapsed,
                    applies_to="topology_only"),
        diagnostics=dict(status="not_evaluated", reason="no_distance_inputs"),
        support=dict(status="not_evaluated", reason="no_replicates"),
        baseline=dict(status="not_evaluated", reason="no_baseline_tree"),
        diversity=dict(status="not_evaluated", reason="no_sample_table"),
        seed=args.seed, selected_pairs=pairs,
        limits={name: getattr(args, name) for name in ("max_tips", "max_pairs", "max_quartets",
                                                      "max_replicates")},
        versions={name: version(name) for name in ("dendropy", "scikit-bio", "numpy", "scipy")},
        inputs={name: _input_identity(path) for name, path in inputs.items()},
    )
    for name in ("taxon_map", "taxa_file", "metadata", "distances", "embedding_vectors",
                 "taxa_metadata", "replicates", "samples"):
        if path := getattr(args, name):
            report["inputs"][name] = _input_identity(path)
    if "baseline" in trees:
        baseline_topology, _ = topology_metrics(trees["baseline"], topology_reference)
        baseline_branches, _ = branch_metrics(
            trees["baseline"], reference, pairs, length_mode=args.length_mode,
            inferred_units=args.baseline_units, reference_units=args.reference_units,
            units_evidence=args.units_evidence,
            original_qc={"inferred": qc["baseline"], "reference": qc["reference"]},
        )
        report["baseline"] = dict(status="evaluated", topology=baseline_topology,
                                  branches=baseline_branches)
    diagnostic_rows = []
    if args.distances or args.embedding_vectors:
        vectors, changed = (
            load_vectors(args.embedding_vectors, taxa) if args.embedding_vectors else (None, False)
        )
        taxonomy = load_taxonomy(args.taxa_metadata, taxa) if args.taxa_metadata else {}
        report["diagnostics"], raw_pairs, diagnostic_rows = embedding_diagnostics(
            inferred, reference, pairs, distances=distances, vectors=vectors, taxonomy=taxonomy,
            same_embedding_units=args.embedding_fit, near_zero=args.near_zero_distance,
            max_quartets=args.max_quartets, seed=args.seed,
            lengths_valid={name: qc[name]["valid"] for name in ("inferred", "reference")},
        )
        report["diagnostics"]["vectors_renormalized"] = changed
        report["diagnostics"]["embedding_units"] = args.embedding_units
        indexed = {(row["taxon_a"], row["taxon_b"]): row for row in pair_rows}
        for row in raw_pairs:
            pair = (row["taxon_a"], row["taxon_b"])
            target = indexed.setdefault(pair, dict(taxon_a=pair[0], taxon_b=pair[1]))
            for key, value in row.items():
                target[f"raw_{key}" if key in {"inferred_distance", "reference_distance"}
                       else key] = value
        pair_rows = [indexed[pair] for pair in sorted(indexed)]
    if args.replicates:
        report["support"] = replicate_support(
            args.replicates, inferred, kind=args.replicate_kind, method=args.replicate_method,
            mode=args.mode, mapping=mappings["inferred"], max_tips=args.max_tips,
            max_replicates=args.max_replicates,
        )
        support = {row["clade_id"]: row for row in report["support"]["clades"]}
        for row in clades:
            if row["clade_id"] in support:
                row.update({
                    f"replicate_{key}": value for key, value in support[row["clade_id"]].items()
                    if key != "clade_id"
                })
    alpha, beta = [], []
    if args.samples:
        if not qc["inferred"]["valid"] or not qc["reference"]["valid"]:
            report["diversity"] = dict(status="not_evaluated", reason="invalid_or_missing_lengths")
        else:
            report["diversity"], alpha, beta = diversity_sensitivity(
                inferred, reference, load_samples(args.samples), length_mode=args.length_mode,
                taxa_policy=args.sample_taxa_policy, backend=args.backend, max_pairs=args.max_pairs,
            )
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _csv(args.output_dir / "taxa.csv", coverage, ["tree", "label", "taxon", "retained", "reason"])
    _csv(args.output_dir / "clades.csv", clades, ["clade_id", "origin", "size", "status"])
    _csv(args.output_dir / "pairs.csv", pair_rows, ["taxon_a", "taxon_b"])
    _csv(args.output_dir / "diagnostics.csv", diagnostic_rows, ["stratum", "method", "count"])
    _csv(args.output_dir / "diversity_alpha_comparison.csv", alpha, ["sample"])
    _csv(args.output_dir / "diversity_beta_comparison.csv", beta, ["sample_a", "sample_b"])
    (args.output_dir / "validation.json").write_text(serialized, encoding="utf-8")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, KeyError, DataParseError) as error:
        parser.error(str(error))
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())