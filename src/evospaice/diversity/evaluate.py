"""Evaluate alpha and beta diversity for samples placed on a reference tree."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

import dendropy
from dendropy.utility.error import DataParseError

from evospaice.diversity.metrics import Backend, Tree, batch_diversity


def load_samples(path: Path) -> dict[str, dict[str, float]]:
    """Load sample abundances from a CSV or TSV file."""
    delimiter = "," if path.suffix.lower() == ".csv" else "\t"
    samples: defaultdict[str, dict[str, float]] = defaultdict(dict)

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        expected = {"sample", "taxon", "abundance"}
        if (reader.fieldnames is None or set(reader.fieldnames) != expected
                or len(reader.fieldnames) != 3):
            raise ValueError("Sample table must have exactly: sample, taxon, abundance")
        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed sample row {row_number}")
            sample_id = row["sample"].strip()
            taxon = row["taxon"].strip()
            if not sample_id or not taxon:
                raise ValueError(f"Missing sample or taxon on row {row_number}")
            if taxon in samples[sample_id]:
                raise ValueError(
                    f"Duplicate sample/taxon pair on row {row_number}: {sample_id}, {taxon}"
                )
            try:
                value = float(row["abundance"])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("Abundance must be finite and non-negative")
                samples[sample_id][taxon] = value
            except ValueError as error:
                raise ValueError(f"Invalid abundance on row {row_number}") from error

    if not samples:
        raise ValueError("Sample table contains no observations")
    return dict(samples)


def evaluate(
    tree: Tree,
    samples: dict[str, dict[str, float]],
    *,
    backend: Backend = "skbio",
    memory_mb: float = 512,
) -> tuple[list[dict[str, str | float]], list[dict[str, str | float]]]:
    """Calculate per-sample alpha and pairwise beta diversity."""
    sample_ids, pd_values, unweighted, weighted = batch_diversity(
        tree, samples, backend=backend, memory_mb=memory_mb
    )
    alpha = [
        {"sample": sample_id, "faith_pd": float(pd_values[index])}
        for index, sample_id in enumerate(sample_ids)
    ]
    beta: list[dict[str, str | float]] = []
    for index, sample_a in enumerate(sample_ids):
        for other, sample_b in enumerate(sample_ids[index + 1 :], start=index + 1):
            beta.append(
                {
                    "sample_a": sample_a,
                    "sample_b": sample_b,
                    "unweighted_unifrac": float(unweighted[index, other]),
                    "weighted_unifrac": float(weighted[index, other]),
                }
            )
    return alpha, beta


def write_results(
    output_dir: Path,
    alpha: list[dict[str, str | float]],
    beta: list[dict[str, str | float]],
) -> None:
    """Write alpha and beta diversity results as CSV files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "alpha_diversity.csv", ["sample", "faith_pd"], alpha)
    _write_csv(
        output_dir / "beta_diversity.csv",
        ["sample_a", "sample_b", "unweighted_unifrac", "weighted_unifrac"],
        beta,
    )


def build_parser(parser: argparse.ArgumentParser | None = None) -> argparse.ArgumentParser:
    if parser is None:
        parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True, help="Branch-length Newick tree")
    parser.add_argument(
        "--samples",
        type=Path,
        required=True,
        help="CSV/TSV with sample, taxon, abundance columns",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--backend", choices=["skbio", "unifrac"], default="skbio")
    parser.add_argument("--memory-mb", type=float, default=512)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (ValueError, DataParseError) as error:
        parser.error(str(error))
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


def run(args: argparse.Namespace) -> int:
    """Run the same evaluation from the package or top-level command."""
    tree = dendropy.Tree.get(
        path=str(args.tree),
        schema="newick",
        preserve_underscores=True,
        rooting="force-rooted",
        taxon_namespace=dendropy.TaxonNamespace(is_case_sensitive=True),
        case_sensitive_taxon_labels=True,
    )
    alpha, beta = evaluate(
        tree, load_samples(args.samples), backend=args.backend, memory_mb=args.memory_mb
    )
    write_results(args.output_dir, alpha, beta)
    packages = ["scikit-bio", "dendropy"] + (["unifrac"] if args.backend == "unifrac" else [])
    manifest = {
        "schema_version": 1,
        "backend": args.backend,
        "versions": {package: version(package) for package in packages},
        "weighted_normalized": True,
        "root_policy": "supplied_study_root_excluding_incoming_stem",
        "inputs": {},
    }
    for name in ("tree", "samples"):
        path = getattr(args, name)
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        manifest["inputs"][name] = {"path": str(path), "sha256": digest}
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0


def _write_csv(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str | float]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
