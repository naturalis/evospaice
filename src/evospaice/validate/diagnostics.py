"""Embedding fidelity and replicate stability on a bounded benchmark set."""

from __future__ import annotations

import csv
import gzip
import itertools
import math
import random
import zipfile
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import dendropy
import numpy as np

from .compare import (
    BoundedNamespace,
    PathDistances,
    branch_qc,
    distance_summary,
    informative_splits,
    leaf_labels,
    prepare_trees,
    split_id,
)

RANKS = ("kingdom", "phylum", "class", "order", "family", "genus", "species")
UNKNOWN = {"", "none", "unknown", "unidentified", "unclassified", "na", "n/a"}


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


def load_distances(path: Path, taxa: set[str]) -> dict[tuple[str, str], dict[str, float]]:
    result = {}
    for row in read_table(path, {"taxon_a", "taxon_b", "embedding_distance"}):
        first, second = row["taxon_a"], row["taxon_b"]
        pair = tuple(sorted((first, second)))
        if first == second or first not in taxa or second not in taxa or pair in result:
            raise ValueError("Distance table has self-pairs, unknown taxa or duplicate pairs")
        values = {}
        for name in ("embedding_distance", "kmer_distance"):
            if name in row:
                value = float(row[name])
                if not math.isfinite(value) or value < 0:
                    raise ValueError("Distances must be finite and non-negative")
                values[name] = value
        result[pair] = values
    return result


def load_vectors(path: Path, taxa: set[str]) -> tuple[dict[str, np.ndarray], bool]:
    """Read a bounded, pickle-free vector export and normalize nonzero vectors."""
    with zipfile.ZipFile(path) as archive:
        if sum(entry.file_size for entry in archive.infolist()) > 256 * 1024**2:
            raise ValueError("Vector archive exceeds 256 MiB decompressed limit")
    with np.load(path, allow_pickle=False) as data:
        labels, vectors = data["taxa"], data["vectors"]
        if labels.ndim != 1 or labels.dtype.kind not in "US":
            raise ValueError("Vector taxa must be a one-dimensional string array")
        labels = labels.tolist()
        if vectors.ndim != 2 or vectors.shape[0] != len(labels) or vectors.shape[1] == 0:
            raise ValueError("Vector dimensions do not match taxa")
        if len(labels) != len(set(labels)) or set(labels) != taxa:
            raise ValueError("Vector taxa must match the retained benchmark taxa exactly")
        vectors = np.asarray(vectors, dtype=np.float64)
        if not np.isfinite(vectors).all():
            raise ValueError("Embedding vectors must be finite")
        scale = np.max(np.abs(vectors), axis=1)
        if np.any(scale == 0):
            raise ValueError("Embedding vectors must have nonzero norm")
        scaled = vectors / scale[:, None]
        norms = np.linalg.norm(scaled, axis=1)
        normalized = scaled / norms[:, None]
        changed = not np.allclose(scale * norms, 1.0, rtol=1e-6, atol=1e-8)
    return dict(zip(labels, normalized, strict=True)), changed


def load_taxonomy(path: Path, taxa: set[str]) -> dict[str, tuple[str | None, ...]]:
    result = {}
    for row in read_table(path, {"taxon"}):
        taxon = row["taxon"]
        if taxon not in taxa or taxon in result:
            raise ValueError("Taxonomy contains unknown or duplicate canonical taxa")
        result[taxon] = tuple(
            None if row.get(rank, "").strip().lower() in UNKNOWN
            else row[rank].strip().casefold() for rank in RANKS
        )
    return result


def pair_stratum(first: str, second: str, taxonomy: Mapping[str, tuple]) -> str:
    left, right = taxonomy.get(first), taxonomy.get(second)
    if left is None or right is None:
        return "unknown"
    deepest = "unknown"
    for index, rank in enumerate(RANKS):
        if left[index] is None or right[index] is None:
            continue
        if left[index] != right[index]:
            break
        deepest = rank
    return deepest


def _quartets(taxa: list[str], maximum: int, seed: int) -> list[tuple[str, ...]]:
    if maximum < 1:
        raise ValueError("max_quartets must be positive")
    total = math.comb(len(taxa), 4) if len(taxa) >= 4 else 0
    if total <= maximum:
        return list(itertools.combinations(taxa, 4))
    rng = random.Random(seed)
    selected = set()
    while len(selected) < maximum:
        selected.add(tuple(sorted(rng.sample(taxa, 4))))
    return sorted(selected)


def embedding_diagnostics(
    inferred: dendropy.Tree, reference: dendropy.Tree,
    pairs: list[tuple[str, str]], *,
    distances: dict[tuple[str, str], dict[str, float]] | None = None,
    vectors: dict[str, np.ndarray] | None = None,
    taxonomy: Mapping[str, tuple] | None = None,
    same_embedding_units: bool = False,
    near_zero: float | None = None, max_quartets: int = 10_000, seed: int = 0,
    lengths_valid: Mapping[str, bool] | None = None,
) -> tuple[dict, list[dict], list[dict]]:
    """Measure rank preservation, reconstruction fit and four-point residuals."""
    if (distances is None) == (vectors is None):
        raise ValueError("Supply exactly one distance table or vector export")
    if near_zero is not None and (not math.isfinite(near_zero) or near_zero < 0):
        raise ValueError("near_zero must be finite and non-negative")
    paths = {}
    for name, tree in (("inferred", inferred), ("reference", reference)):
        valid = (lengths_valid or {}).get(name, branch_qc(tree)["valid"])
        if valid:
            paths[name] = PathDistances(tree)

    def values(pair):
        if vectors is not None:
            return {"embedding_distance": float(np.clip(
                1 - np.dot(vectors[pair[0]], vectors[pair[1]]), 0, 2
            ))}
        assert distances is not None
        return distances.get(tuple(sorted(pair)))

    rows = []
    for first, second in pairs:
        measurements = values((first, second))
        if measurements is None:
            continue
        row = dict(taxon_a=first, taxon_b=second,
                   stratum=pair_stratum(first, second, taxonomy or {}), **measurements)
        for name, path in paths.items():
            row[f"{name}_distance"] = path.distance(first, second)
        if reference.is_rooted and "reference" in paths:
            ancestor = reference.mrca(taxon_labels=[first, second], is_bipartitions_updated=True)
            row["reference_mrca_depth"] = paths["reference"].depths[ancestor]
        rows.append(row)
    summaries = []
    groups = defaultdict(list)
    groups["all"] = rows
    for row in rows:
        groups[row["stratum"]].append(row)
    depth_boundaries = []
    if rows and "reference_mrca_depth" in rows[0]:
        depth_boundaries = np.unique(np.quantile(
            [row["reference_mrca_depth"] for row in rows], [.25, .5, .75]
        )).tolist()
        for row in rows:
            bucket = int(np.searchsorted(
                depth_boundaries, row["reference_mrca_depth"], side="right"
            ))
            row["depth_bin"] = bucket
            groups[f"reference_depth_bin_{bucket}"].append(row)
    for stratum, members in sorted(groups.items()):
        for method in ("embedding_distance", "kmer_distance"):
            matched = [row for row in members if method in row]
            if not matched:
                continue
            observed = np.array([row[method] for row in matched])
            summary = dict(stratum=stratum, method=method, count=len(matched),
                           minimum=float(observed.min()), median=float(np.median(observed)),
                           q10=float(np.quantile(observed, .1)),
                           q90=float(np.quantile(observed, .9)),
                           zero_fraction=float(np.mean(observed == 0)))
            if near_zero is not None and method == "embedding_distance":
                summary["near_zero_fraction"] = float(np.mean(observed <= near_zero))
            if "reference" in paths:
                reference_summary = distance_summary(
                    observed, [row["reference_distance"] for row in matched], errors=False
                )
                summary.update({
                    f"reference_{key}": value for key, value in reference_summary.items()
                })
            summaries.append(summary)
    fit: dict[str, Any] = {
        "status": "not_evaluated", "reason": "embedding_units_not_declared_compatible"
    }
    if same_embedding_units and "inferred" in paths and rows:
        direct = [row["embedding_distance"] for row in rows]
        predicted = [row["inferred_distance"] for row in rows]
        fit = dict(status="evaluated", interpretation="in_sample_reconstruction_fit",
                   **distance_summary(predicted, direct, errors=True))
        denominator = float(np.linalg.norm(direct))
        fit["normalized_stress"] = float(np.linalg.norm(np.subtract(predicted, direct))) / (
            denominator
        ) if denominator else None
    elif same_embedding_units:
        fit = dict(status="not_evaluated", reason="missing_lengths_or_pairs")
    gaps, scaled_gaps = [], []
    quartets = _quartets(sorted(leaf_labels(inferred)), max_quartets, seed)
    for quartet in quartets:
        pair_values = {pair: values(pair) for pair in itertools.combinations(quartet, 2)}
        if any(value is None for value in pair_values.values()):
            continue
        complete_values = {pair: value for pair, value in pair_values.items() if value is not None}
        first, second, third, fourth = quartet
        sums = sorted(
            (complete_values[left]["embedding_distance"]
             + complete_values[right]["embedding_distance"])
            for left, right in (
                ((first, second), (third, fourth)),
                ((first, third), (second, fourth)),
                ((first, fourth), (second, third)),
            )
        )
        gaps.append(sums[2] - sums[1])
        scaled_gaps.append((sums[2] - sums[1]) / sums[2] if sums[2] else 0.0)
    quartet_summary = dict(
        requested=len(quartets), complete=len(gaps), skipped=len(quartets) - len(gaps),
        mean_gap=float(np.mean(gaps)) if gaps else None,
        mean_relative_gap=float(np.mean(scaled_gaps)) if gaps else None,
    )
    return dict(status="evaluated", selected_pairs=len(pairs), observed_pairs=len(rows),
                unknown_taxonomy_pairs=sum(row["stratum"] == "unknown" for row in rows),
                within_species_pairs=sum(row["stratum"] == "species" for row in rows),
                near_zero_threshold=near_zero, reconstruction_fit=fit, quartets=quartet_summary,
                reference_depth_bin_boundaries=depth_boundaries,
                kmer_control="evaluated" if any("kmer_distance" in row for row in rows)
                else "not_evaluated"), rows, summaries


def replicate_support(
    path: Path, inferred: dendropy.Tree, *, kind: str, method: str,
    mode: str, mapping: Mapping[str, str] | None = None,
    max_tips: int = 5000, max_replicates: int = 1000,
) -> dict:
    """Stream supplied trees and count each target split once per replicate."""
    if kind not in {"bootstrap", "perturbation", "other"} or not method.strip():
        raise ValueError("Replicate kind and a nonempty resampling method are required")
    if max_replicates < 1:
        raise ValueError("max_replicates must be positive")
    targets = {split_id(mask, inferred): 0 for mask in informative_splits(inferred)}
    count = 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        for replicate in dendropy.Tree.yield_from_files(
            [handle], schema="newick", preserve_underscores=True, case_sensitive_taxon_labels=True,
            taxon_namespace=BoundedNamespace(max_tips),
        ):
            count += 1
            if count > max_replicates:
                raise ValueError("Replicate limit exceeded")
            labels = {mapping.get(label, label) if mapping else label for label in leaf_labels(
                replicate
            )}
            if not leaf_labels(inferred) <= labels:
                raise ValueError("Every replicate must contain all benchmark taxa")
            aligned, _, _ = prepare_trees(
                {"inferred": inferred, "replicate": replicate}, mode=mode,
                taxa_policy="intersection", mappings={"replicate": mapping or {}},
                max_tips=max_tips,
            )
            present = {split_id(mask, aligned["replicate"]) for mask in informative_splits(
                aligned["replicate"]
            )}
            for identifier in targets:
                targets[identifier] += int(identifier in present)
    if not count:
        raise ValueError("Replicate input contains no trees")
    return dict(
        status="evaluated", kind=kind, method=method, replicates=count,
        clades=[dict(clade_id=identifier, count=observed, total=count, support=observed / count)
                for identifier, observed in sorted(targets.items())],
    )