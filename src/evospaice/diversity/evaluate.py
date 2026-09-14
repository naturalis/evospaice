"""Evaluate alpha and beta diversity for samples placed on a reference tree."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import dendropy

from evospaice.diversity.metrics import faith_pd, unweighted_unifrac, weighted_unifrac


def load_samples(path: Path) -> dict[str, dict[str, float]]:
    """Load sample abundances from a CSV or TSV file."""
    delimiter = "," if path.suffix.lower() == ".csv" else "\t"
    samples: defaultdict[str, dict[str, float]] = defaultdict(dict)

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        expected = {"sample", "taxon", "abundance"}
        if reader.fieldnames is None or set(reader.fieldnames) != expected:
            raise ValueError("Sample table must have exactly: sample, taxon, abundance")
        for row_number, row in enumerate(reader, start=2):
            sample_id = row["sample"].strip()
            taxon = row["taxon"].strip()
            if not sample_id or not taxon:
                raise ValueError(f"Missing sample or taxon on row {row_number}")
            if taxon in samples[sample_id]:
                raise ValueError(
                    f"Duplicate sample/taxon pair on row {row_number}: {sample_id}, {taxon}"
                )
            try:
                samples[sample_id][taxon] = float(row["abundance"])
            except ValueError as error:
                raise ValueError(f"Invalid abundance on row {row_number}") from error

    if not samples:
        raise ValueError("Sample table contains no observations")
    return dict(samples)


def evaluate(
    tree: dendropy.Tree,
    samples: dict[str, dict[str, float]],
) -> tuple[list[dict[str, str | float]], list[dict[str, str | float]]]:
    """Calculate per-sample alpha and pairwise beta diversity."""
    sample_ids = sorted(samples)
    alpha = [
        {"sample": sample_id, "faith_pd": faith_pd(tree, samples[sample_id])}
        for sample_id in sample_ids
    ]
    beta: list[dict[str, str | float]] = []
    for index, sample_a in enumerate(sample_ids):
        for sample_b in sample_ids[index + 1 :]:
            beta.append(
                {
                    "sample_a": sample_a,
                    "sample_b": sample_b,
                    "unweighted_unifrac": unweighted_unifrac(
                        tree, samples[sample_a], samples[sample_b]
                    ),
                    "weighted_unifrac": weighted_unifrac(
                        tree, samples[sample_a], samples[sample_b]
                    ),
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True, help="Branch-length Newick tree")
    parser.add_argument(
        "--samples",
        type=Path,
        required=True,
        help="CSV/TSV with sample, taxon, abundance columns",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tree = dendropy.Tree.get(
        path=str(args.tree),
        schema="newick",
        preserve_underscores=True,
        rooting="force-rooted",
    )
    alpha, beta = evaluate(tree, load_samples(args.samples))
    write_results(args.output_dir, alpha, beta)
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
