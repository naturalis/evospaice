"""Generate an interactive scatterplot from original embeddings and a reference tree."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import logging
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dendropy
import numpy as np
import scipy
from scipy.stats import pearsonr, spearmanr

LOGGER = logging.getLogger(__name__)


REQUIRED_KEYS = ("embeddings", "ids", "bin_uri", "species", "genus", "family", "order")


TAXONOMY_RANKS = ("species", "genus", "family", "order")


@dataclass
class Dataset:
    embeddings: np.ndarray
    metadata: dict[str, np.ndarray]
    source_rows: np.ndarray
    schema: dict[str, dict[str, Any]]
    original_count: int
    literal_removed_count: int

    def __len__(self) -> int:
        return len(self.source_rows)

    def take(self, indices: np.ndarray) -> Dataset:
        return Dataset(
            self.embeddings[indices],
            {key: values[indices] for key, values in self.metadata.items()},
            self.source_rows[indices],
            self.schema,
            self.original_count,
            self.literal_removed_count,
        )


def diagnostic(data: Dataset, index: int, field: str, reason: str) -> dict[str, Any]:
    return {
        "source_row": int(data.source_rows[index]),
        "record_id": str(data.metadata["ids"][index]),
        "field": field,
        "reason": reason,
    }


def missing_reason(value: Any) -> str | None:
    """Keep actual nulls, blank labels and literal sentinels distinguishable."""
    if value is None or (isinstance(value, (float, np.floating)) and np.isnan(value)):
        return "actual_null"
    if isinstance(value, (str, np.str_)):
        if not value.strip():
            return "blank"
        if value == "None":
            return "literal_none"
    return None


def validate_retained(data: Dataset, diagnostics: list[dict[str, Any]]) -> None:
    """Fatal quality checks; never called on the pre-filter source arrays."""
    errors: list[dict[str, Any]] = []
    finite = np.isfinite(data.embeddings).all(axis=1)
    nonzero = np.any(data.embeddings != 0, axis=1)
    for index in np.flatnonzero(~finite | ~nonzero):
        reason = "non_finite_vector" if not finite[index] else "zero_norm_vector"
        errors.append(diagnostic(data, int(index), "embeddings", reason))
    for field in ("ids", "bin_uri"):
        seen: dict[str, int] = {}
        for index, value in enumerate(data.metadata[field]):
            if missing_reason(value) or not isinstance(value, (str, np.str_)):
                errors.append(diagnostic(data, index, field, "invalid_identifier"))
                continue
            if value in seen:
                first = seen[value]
                errors.append(
                    diagnostic(
                        data,
                        index,
                        field,
                        f"duplicate_identifier; first_source_row={data.source_rows[first]}",
                    )
                )
            else:
                seen[value] = index
    if errors:
        diagnostics.extend(errors)
        raise ValueError(f"Invalid retained records ({len(errors)} errors): {errors[:5]}")


def load_dataset(path: str | Path, diagnostics: list[dict[str, Any]] | None = None) -> Dataset:
    """Load without pickle; structural checks precede the mandatory exact mask.

    Every extra key is treated as row-aligned metadata and validated accordingly.
    Excluded IDs are accessed only to record the mandatory filtering decision.
    """
    if diagnostics is None:
        diagnostics = []
    loaded = np.load(path, allow_pickle=False)
    if not isinstance(loaded, np.lib.npyio.NpzFile):
        raise ValueError("Input must be an NPZ archive, not a standalone array")
    with loaded as archive:
        missing = sorted(set(REQUIRED_KEYS) - set(archive.files))
        if missing:
            raise ValueError(f"Missing required NPZ keys: {missing}; available: {archive.files}")
        try:
            arrays = {key: archive[key] for key in archive.files}
        except ValueError as exc:
            raise ValueError(f"NPZ arrays must be readable without pickle: {exc}") from exc
    schema = {
        key: {"shape": list(value.shape), "dtype": str(value.dtype)}
        for key, value in arrays.items()
    }
    LOGGER.info("NPZ structural schema: %s", schema)
    embeddings = arrays["embeddings"]
    if embeddings.ndim != 2 or 0 in embeddings.shape or embeddings.dtype.kind not in "iuf":
        raise ValueError("embeddings must be a non-empty real numeric two-dimensional array")
    count = len(embeddings)
    for key, values in arrays.items():
        if key != "embeddings" and (values.ndim != 1 or len(values) != count):
            raise ValueError(
                f"Metadata {key!r} must be one-dimensional with {count} rows; got {values.shape}"
            )

    # No content/quality/taxonomy inspection may precede these aligned masks.
    keep = arrays["species"] != "None"
    if np.ndim(keep) == 0:
        keep = np.full(count, bool(keep), dtype=bool)
    source_rows = np.flatnonzero(keep)
    retained_embeddings = embeddings[keep]
    retained_metadata = {key: values[keep] for key, values in arrays.items() if key != "embeddings"}
    removed_rows = np.flatnonzero(~keep)
    removed_ids = arrays["ids"][~keep]
    del arrays, embeddings
    diagnostics.extend(
        {
            "source_row": int(row),
            "record_id": str(record_id),
            "field": "species",
            "reason": "exact_species_None",
        }
        for row, record_id in zip(removed_rows, removed_ids, strict=True)
    )
    data = Dataset(
        retained_embeddings, retained_metadata, source_rows, schema, count, len(removed_rows)
    )
    LOGGER.info(
        "Filter species == 'None': original=%d removed=%d remaining=%d",
        count,
        len(removed_rows),
        len(data),
    )
    validate_retained(data, diagnostics)
    return data


def normalize_embeddings(embeddings: np.ndarray) -> np.ndarray:
    if np.iscomplexobj(embeddings):
        raise ValueError("Embeddings must be real")
    vectors = np.asarray(embeddings, dtype=np.float64)
    if vectors.ndim != 2 or 0 in vectors.shape:
        raise ValueError("Expected non-empty two-dimensional embeddings")
    if not np.isfinite(vectors).all():
        raise ValueError("Non-finite embeddings")
    # Scaling before taking the norm avoids overflow/underflow for finite inputs.
    scales = np.max(np.abs(vectors), axis=1, keepdims=True)
    if np.any(scales == 0):
        raise ValueError("Zero-norm embeddings")
    scaled = vectors / scales
    return scaled / np.linalg.norm(scaled, axis=1, keepdims=True)


def cosine_distance_matrix(embeddings: np.ndarray) -> np.ndarray:
    unit = normalize_embeddings(embeddings)
    distances = np.clip(1.0 - unit @ unit.T, 0.0, 2.0)
    np.fill_diagonal(distances, 0.0)
    return distances


def cosine_distance(unit_left: np.ndarray, unit_right: np.ndarray) -> float:
    """Distance between already normalised vectors; no global matrix is allocated."""
    left = np.asarray(unit_left, dtype=np.float64)
    right = np.asarray(unit_right, dtype=np.float64)
    return float(np.clip(1.0 - np.dot(left, right), 0.0, 2.0))


def read_reference(reference_path: Path) -> dendropy.Tree:
    with reference_path.open(encoding="utf-8-sig") as handle:
        prefix = handle.read(20).lstrip().upper()
    trees = dendropy.TreeList.get(
        path=str(reference_path),
        schema="nexus" if prefix.startswith("#NEXUS") else "newick",
        preserve_underscores=True,
    )
    if len(trees) != 1:
        raise ValueError("Reference file must contain exactly one tree")
    return trees[0]


class ReferenceDistances:
    """Binary-lifting LCA indexing without an all-reference-pairs distance matrix."""

    def __init__(self, tree: dendropy.Tree):
        nodes = list(tree.preorder_node_iter())
        indices = {node: index for index, node in enumerate(nodes)}
        self.records: dict[str, int] = {}
        self.depth = np.zeros(len(nodes), dtype=np.int32)
        self.distance = np.zeros(len(nodes), dtype=np.float64)
        self.unknown = np.zeros(len(nodes), dtype=np.int32)
        parents = np.zeros(len(nodes), dtype=np.int32)
        self.missing_edges = 0
        for index, node in enumerate(nodes):
            if node.is_leaf():
                label = node.taxon.label if node.taxon is not None else node.label
                if not label or label in self.records:
                    raise ValueError("Reference tips require unique nonempty record IDs")
                self.records[label] = index
            if node.parent_node is None:
                continue
            parent = indices[node.parent_node]
            parents[index] = parent
            self.depth[index] = self.depth[parent] + 1
            length = node.edge_length
            if length is not None and (not np.isfinite(length) or length < 0):
                raise ValueError(f"Invalid reference branch length at node {index}: {length}")
            self.missing_edges += length is None
            self.unknown[index] = self.unknown[parent] + (length is None)
            # Count unknowns separately: they are never resolved zero-length paths.
            self.distance[index] = self.distance[parent] + (0.0 if length is None else length)
        self.ancestors = [parents]
        for _ in range(1, max(1, int(self.depth.max()).bit_length())):
            previous = self.ancestors[-1]
            self.ancestors.append(previous[previous])

    def pair_distances(self, left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a, b = np.asarray(left, dtype=np.int32).copy(), np.asarray(right, dtype=np.int32).copy()
        swap = self.depth[a] < self.depth[b]
        a[swap], b[swap] = b[swap], a[swap]
        difference = self.depth[a] - self.depth[b]
        for level, ancestors in enumerate(self.ancestors):
            move = (difference & (1 << level)) != 0
            a[move] = ancestors[a[move]]
        for ancestors in reversed(self.ancestors):
            move = ancestors[a] != ancestors[b]
            a[move], b[move] = ancestors[a[move]], ancestors[b[move]]
        lca = np.where(a == b, a, self.ancestors[0][a])
        valid = self.unknown[left] + self.unknown[right] - 2 * self.unknown[lca] == 0
        distance = self.distance[left] + self.distance[right] - 2 * self.distance[lca]
        tolerance = 1e-12 * max(1.0, float(self.distance.max()))
        if np.any(distance[valid] < -tolerance):
            raise ValueError("Reference path calculation produced a negative resolved distance")
        distance = np.maximum(distance, 0.0)
        distance[~valid] = np.nan
        return distance, valid


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar_text(value: Any) -> str | None:
    if isinstance(value, np.generic):
        value = value.item()
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("CSV metadata must be finite or explicitly missing")
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ValueError(f"Expected scalar CSV metadata, got {type(value).__name__}")


class Exporter:
    """Only remove files created by this run if an export fails."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.created: list[Path] = []

    def csv(self, name: str, fields: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
        path = self.output_dir / name
        with path.open("x", encoding="utf-8", newline="") as handle:
            self.created.append(path)
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: scalar_text(value) for key, value in row.items()})

    def json(self, name: str, payload: dict[str, Any]) -> None:
        self.text(name, json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n")

    def text(self, name: str, content: str) -> None:
        path = self.output_dir / name
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            self.created.append(path)
            handle.write(content)

    def npz(self, name: str, **arrays: np.ndarray) -> None:
        path = self.output_dir / name
        with path.open("xb") as handle:
            self.created.append(path)
            np.savez_compressed(handle, **arrays)

    def remove_success_artifacts(self) -> None:
        for path in self.created:
            path.unlink()
        self.created.clear()


RANK_PATHS = {
    "family": ("family",),
    "genus": ("family", "genus"),
    "species": ("family", "genus", "species"),
}


COLOR_MODES = ("relationship", *RANK_PATHS)


PLURALS = {"family": "families", "genus": "genera", "species": "species"}


def taxonomy_colors(
    rows: list[dict[str, Any]], default_mode: str = "relationship"
) -> dict[str, Any]:
    if default_mode not in COLOR_MODES:
        raise ValueError(f"Unknown color mode: {default_mode}")
    result: dict[str, Any] = {"default_mode": default_mode, "ranks": {}}
    for rank, fields in RANK_PATHS.items():
        paths = []
        for row in rows:
            values = tuple(row.get(field) for field in fields)
            if any(missing_reason(value) is not None for value in values):
                paths.append(None)
            elif not all(isinstance(value, str) for value in values):
                raise ValueError("Taxonomy labels must be strings or missing values")
            else:
                paths.append(values)
        keys = sorted({path for path in paths if path is not None})
        indices = {key: index + 2 for index, key in enumerate(keys)}
        categories = [
            {"label": f"Unknown/incomplete {rank} taxonomy", "color": "#c3ccd7"},
            {"label": f"Different {PLURALS[rank]}", "color": "#8591a3"},
        ]
        for key in keys:
            identity = json.dumps([rank, *key], ensure_ascii=True, separators=(",", ":"))
            digest = hashlib.sha256(identity.encode("utf-8")).digest()
            hue = int.from_bytes(digest[:2], "big") % 360
            color = f"hsl({hue}, {55 + digest[2] % 20}%, {35 + digest[3] % 15}%)"
            label = key[-1] if len(key) == 1 else f"{key[-1]} ({' > '.join(key[:-1])})"
            categories.append({"label": label, "color": color})
        result["ranks"][rank] = {
            "categories": categories,
            "record_codes": [0 if path is None else indices[path] for path in paths],
        }
    return result


KNOWN_OMNI20M_SHA256 = "b9c77c3beb23a3c7ab0fcb187b0c746ad095f8a661851fdb6b02bae812e2e1ec"


RELATIONSHIPS = (
    "Same species label (different BINs)",
    "Same genus, different species",
    "Same family, different genera",
    "Different families",
    "Unknown taxonomy relationship",
)


SAMPLE_FIELDS = (
    "sample_index",
    "source_row",
    "record_id",
    "bin_id",
    "species",
    "genus",
    "family",
    "order",
)


def correlation_metrics(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    if len(x) != len(y) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Correlation inputs must be aligned and finite")
    result: dict[str, Any] = {
        "count": len(x),
        "pearson": None,
        "spearman": None,
        "regression": None,
    }
    if len(x) < 2:
        result["reason"] = "Fewer than two valid pairs"
        return result
    x_variable, y_variable = np.ptp(x) > 0, np.ptp(y) > 0
    if x_variable:
        centered = x - x.mean()
        slope = float(np.dot(centered, y - y.mean()) / np.dot(centered, centered))
        result["regression"] = {"slope": slope, "intercept": float(y.mean() - slope * x.mean())}
    if x_variable and y_variable:
        result["pearson"] = float(pearsonr(x, y).statistic)
        result["spearman"] = float(spearmanr(x, y).statistic)
    else:
        result["reason"] = "At least one distance array is constant"
    return result


def pair_relationships(
    rows: list[dict[str, Any]], left: np.ndarray, right: np.ndarray
) -> np.ndarray:
    result = np.full(len(left), 4, dtype=np.uint8)
    labels = {
        rank: np.asarray([row[rank] for row in rows]) for rank in ("species", "genus", "family")
    }
    known = {
        rank: np.asarray([missing_reason(value) is None for value in values])
        for rank, values in labels.items()
    }
    same = {rank: values[left] == values[right] for rank, values in labels.items()}
    family_known = known["family"][left] & known["family"][right]
    genus_known = known["genus"][left] & known["genus"][right]
    result[family_known & ~same["family"]] = 3
    result[family_known & same["family"] & genus_known & ~same["genus"]] = 2
    result[family_known & same["family"] & genus_known & same["genus"]] = 1
    result[known["species"][left] & known["species"][right] & same["species"]] = 0
    return result


def packed(array: np.ndarray, dtype: str, kind: str) -> dict[str, str]:
    return {
        "kind": kind,
        "base64": base64.b64encode(np.asarray(array, dtype=dtype).tobytes()).decode(),
    }


def relationship_selection_metrics(
    x: np.ndarray, y: np.ndarray, relationship: np.ndarray
) -> dict[str, dict[str, Any]]:
    """Cache exact pooled correlations for all 32 legend selections, including none."""
    flags = np.left_shift(np.uint32(1), relationship.astype(np.uint32))
    present = int(np.bitwise_or.reduce(flags, initial=np.uint32(0)))
    cache: dict[int, dict[str, Any]] = {}
    result = {}
    for mask in range(1 << len(RELATIONSHIPS)):
        effective = mask & present
        if effective not in cache:
            include = (flags & effective) != 0
            cache[effective] = correlation_metrics(x[include], y[include])
        result[str(mask)] = cache[effective]
    return result


def render_scatter(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    encoded = encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("scatter.html").read_text(encoding="utf-8")
    return template.replace("__SCATTER_DATA__", encoded)


def run_experiment(
    input_path: Path,
    reference_path: Path,
    output_dir: Path,
    sample_size: int = 1000,
    seed: int = 42,
    *,
    family: str | None = None,
    genus: str | None = None,
    all_matches: bool = False,
    embedding_model: str | None = None,
    color_by: str = "relationship",
    max_pairs: int = 2_000_000,
) -> dict[str, Any]:
    if sample_size < 2 or seed < 0:
        raise ValueError("sample_size must be >= 2 and seed must be nonnegative")
    if family is not None and missing_reason(family) is not None:
        raise ValueError("family must be a nonmissing taxonomy label")
    if genus is not None and missing_reason(genus) is not None:
        raise ValueError("genus must be a nonmissing taxonomy label")
    if max_pairs < 1:
        raise ValueError("max_pairs must be positive")
    if color_by not in COLOR_MODES:
        raise ValueError(f"Unknown color mode: {color_by}")
    if embedding_model is not None and missing_reason(embedding_model) is not None:
        raise ValueError("embedding_model must be a nonmissing model label")
    if output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise ValueError(f"Refusing nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    exporter = Exporter(output_dir)
    try:
        source_hash, reference_hash = sha256_file(input_path), sha256_file(reference_path)
        data = load_dataset(input_path)
        reference = ReferenceDistances(read_reference(reference_path))
        usable = [
            index
            for index, species in enumerate(data.metadata["species"])
            if missing_reason(species) is None
        ]
        matches = sorted(
            (index for index in usable if data.metadata["ids"][index] in reference.records),
            key=lambda index: str(data.metadata["ids"][index]),
        )
        global_match_count = len(matches)
        family_inferred = False
        if genus is not None and family is None:
            parents = {
                str(data.metadata["family"][index])
                for index in usable
                if data.metadata["genus"][index] == genus
            }
            if len(parents) != 1 or missing_reason(next(iter(parents))) is not None:
                raise ValueError(
                    f"Genus {genus!r} has ambiguous, unknown or absent parent family; "
                    "specify --family explicitly"
                )
            family = next(iter(parents))
            family_inferred = True
        eligible = usable
        if family is not None:
            eligible = [index for index in usable if data.metadata["family"][index] == family]
            matches = [index for index in matches if data.metadata["family"][index] == family]
        if genus is not None:
            eligible = [index for index in eligible if data.metadata["genus"][index] == genus]
            matches = [index for index in matches if data.metadata["genus"][index] == genus]
        if all_matches:
            sample_size = len(matches)
            if sample_size < 2:
                raise ValueError("At least two exact matches are required in the selected scope")
        if len(matches) < sample_size:
            raise ValueError(
                f"Requested {sample_size} records but only {len(matches)} exact matches"
            )
        pair_count = sample_size * (sample_size - 1) // 2
        if pair_count > max_pairs:
            raise ValueError(
                f"{sample_size:,} records create {pair_count:,} pairs, exceeding "
                f"max_pairs={max_pairs:,}. Reduce --sample-size, restrict --family/--genus, "
                "or explicitly raise --max-pairs after checking memory requirements."
            )
        chosen = (
            np.arange(len(matches))
            if all_matches
            else np.sort(
                np.random.default_rng(seed).choice(len(matches), sample_size, replace=False)
            )
        )
        sample = data.take(np.asarray(matches)[chosen])
        LOGGER.info(
            "Matched %d records in scope; analyzing %d (%s)",
            len(matches),
            sample_size,
            "all matches" if all_matches else f"seed {seed}",
        )
        rows = [
            {
                "sample_index": index,
                "source_row": int(sample.source_rows[index]),
                "record_id": str(sample.metadata["ids"][index]),
                "bin_id": str(sample.metadata["bin_uri"][index]),
                **{
                    rank: str(sample.metadata[rank][index])
                    for rank in ("species", "genus", "family", "order")
                },
            }
            for index in range(sample_size)
        ]
        left, right = np.triu_indices(sample_size, 1)
        tip_indices = np.asarray([reference.records[row["record_id"]] for row in rows])
        tree_distance, valid = reference.pair_distances(tip_indices[left], tip_indices[right])
        embedding_distance = cosine_distance_matrix(sample.embeddings)[left, right]
        relationship = pair_relationships(rows, left, right)
        selections = relationship_selection_metrics(
            tree_distance[valid], embedding_distance[valid], relationship[valid]
        )
        metrics = {
            "all": selections[str((1 << len(RELATIONSHIPS)) - 1)],
            **{str(code): selections[str(1 << code)] for code in range(len(RELATIONSHIPS))},
        }
        coverage = []
        genus_metrics = []
        if family is not None:
            eligible_counts = Counter(str(data.metadata["genus"][index]) for index in eligible)
            matched_counts = Counter(str(data.metadata["genus"][index]) for index in matches)
            analyzed_counts = Counter(row["genus"] for row in rows)
            coverage = [
                {
                    "family": family,
                    "genus": genus_name,
                    "embedding_records": count,
                    "reference_matched_records": matched_counts[genus_name],
                    "analyzed_records": analyzed_counts[genus_name],
                }
                for genus_name, count in sorted(eligible_counts.items())
            ]
            genus_labels = np.asarray([row["genus"] for row in rows])
            for genus_name, count in sorted(analyzed_counts.items()):
                if missing_reason(genus_name) is not None:
                    continue
                include = (
                    valid & (genus_labels[left] == genus_name) & (genus_labels[right] == genus_name)
                )
                genus_metrics.append(
                    {
                        "genus": genus_name,
                        "record_count": count,
                        "relationship_selection_metrics": relationship_selection_metrics(
                            tree_distance[include],
                            embedding_distance[include],
                            relationship[include],
                        ),
                    }
                )
        summary = {
            "status": "success",
            "input_file": str(input_path.resolve()),
            "reference_file": str(reference_path.resolve()),
            "input_sha256": source_hash,
            "reference_sha256": reference_hash,
            "embedding_model": embedding_model
            or ("omni-dna-20m" if source_hash == KNOWN_OMNI20M_SHA256 else None),
            "embedding_dimensions": int(sample.embeddings.shape[1]),
            "versions": {
                "numpy": np.__version__,
                "scipy": scipy.__version__,
                "dendropy": dendropy.__version__,
            },
            "filtering": {
                "original_embedding_records": data.original_count,
                "literal_species_None_removed": data.literal_removed_count,
                "post_literal_records": len(data),
                "additional_missing_species_removed": len(data) - len(usable),
                "reference_tip_count": len(reference.records),
                "usable_embedding_records": len(usable),
                "exact_matched_records": len(matches),
                "exact_matched_records_before_scope": global_match_count,
                "usable_embedding_records_not_in_reference": len(usable) - global_match_count,
                "scope_eligible_embedding_records": len(eligible),
                "scope_embedding_records_not_in_reference": len(eligible) - len(matches),
            },
            "scope": {
                "family": family,
                "genus": genus,
                "family_inferred": family_inferred,
                "genus_coverage": coverage,
            },
            "color_by": color_by,
            "genus_metrics": genus_metrics,
            "sampling": {
                "record_count": sample_size,
                "seed": None if all_matches else seed,
                "all_matches": all_matches,
                "method": (
                    "All exact record-ID matches in the selected scope, sorted lexicographically"
                    if all_matches
                    else "Uniform sample without replacement from lexicographically sorted "
                    "exact record-ID matches"
                ),
                "unique_species": len({row["species"] for row in rows}),
                "unique_genera": len({row["genus"] for row in rows}),
                "unique_families": len({row["family"] for row in rows}),
                "leaf_semantics": (
                    "Species-labelled BIN representatives; repeated species labels "
                    "remain distinct records"
                ),
            },
            "pairs": {
                "sample_pair_count": len(left),
                "valid_pair_count": int(valid.sum()),
                "unresolved_reference_path_count": int((~valid).sum()),
                "reference_missing_edge_count": reference.missing_edges,
                "exhaustive_within_sample": True,
                "max_pairs": max_pairs,
            },
            "relationships": list(RELATIONSHIPS),
            "metrics": metrics,
            "relationship_selection_metrics": selections,
            "distance_policy": (
                "Direct reference patristic paths versus cosine distances of original "
                "L2-normalized embeddings. No NJ/fitted tree, representative recomputation "
                "or global distance matrix."
            ),
            "interpretation": (
                "Units differ, so no identity line or raw cross-unit RMSE. Pearson tests linear "
                "association; Spearman tests monotonic association. Pairs share sampled records "
                "are not independent; no naive pair-level p-values or confidence intervals."
            ),
            "unknown_path_policy": (
                "Missing reference lengths exclude only pairs crossing those edges; "
                "NPZ NaN is accompanied by valid_reference_path=False"
            ),
        }
        index_dtype, index_kind = ("<u2", "u16") if sample_size <= 65536 else ("<u4", "u32")
        payload = {
            "summary": summary,
            "records": rows,
            "taxonomy_colors": taxonomy_colors(rows, default_mode=color_by),
            "arrays": {
                "left": packed(left[valid], index_dtype, index_kind),
                "right": packed(right[valid], index_dtype, index_kind),
                "reference": packed(tree_distance[valid], "<f8", "f64"),
                "embedding": packed(embedding_distance[valid], "<f8", "f64"),
                "relationship": packed(relationship[valid], "u1", "u8"),
            },
        }
        exporter.text("scatter.html", render_scatter(payload))
        exporter.csv("sampled_records.csv", SAMPLE_FIELDS, rows)
        if family is not None:
            exporter.csv(
                "genus_coverage.csv",
                [
                    "family",
                    "genus",
                    "embedding_records",
                    "reference_matched_records",
                    "analyzed_records",
                ],
                coverage,
            )
        exporter.npz(
            "pairwise_distances.npz",
            sample_i=left,
            sample_j=right,
            reference_tree_distance=tree_distance,
            embedding_cosine_distance=embedding_distance,
            relationship=relationship,
            valid_reference_path=valid,
        )
        if sha256_file(input_path) != source_hash or sha256_file(reference_path) != reference_hash:
            raise ValueError("Source input changed during the experiment")
        summary["inputs_unchanged"] = True
        summary["output_files"] = [*(path.name for path in exporter.created), "summary.json"]
        exporter.json("summary.json", summary)
        return summary
    except Exception as exc:
        exporter.remove_success_artifacts()
        exporter.json(
            "failure.json",
            {"status": "failed", "error": str(exc), "error_type": type(exc).__name__},
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Embedding NPZ archive")
    parser.add_argument(
        "--reference", type=Path, required=True, help="Reference Newick or Nexus tree"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs") / "eda",
        help="New or empty output directory (default: outputs/eda)",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--sample-size",
        type=int,
        default=1000,
        help="Matched records to sample, not pairs (default: 1000)",
    )
    selection.add_argument(
        "--all-matches",
        action="store_true",
        help="Include all matches in the selected scope",
    )
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed (default: 42)")
    parser.add_argument("--family", help="Exact family label")
    parser.add_argument("--genus", help="Exact genus label; infer its family if unambiguous")
    parser.add_argument("--embedding-model", help="Display/provenance label; does not load a model")
    parser.add_argument("--color-by", choices=COLOR_MODES, default="relationship")
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=2_000_000,
        help="Reject larger pair sets before allocation; raising this increases RAM/HTML size",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_experiment(
        args.input,
        args.reference,
        args.output_dir,
        args.sample_size,
        args.seed,
        family=args.family,
        genus=args.genus,
        all_matches=args.all_matches,
        embedding_model=args.embedding_model,
        color_by=args.color_by,
        max_pairs=args.max_pairs,
    )
    print(
        json.dumps(
            {
                "html": str((args.output_dir / "scatter.html").resolve()),
                "records": result["sampling"]["record_count"],
                "pairs": result["pairs"],
                "metrics": result["metrics"]["all"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
