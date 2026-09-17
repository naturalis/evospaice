"""Compare the survey's five representations on one fixed real genus cohort."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import Counter
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path

import numpy as np
from Bio import Phylo
from Bio.Phylo.BaseTree import Clade, Tree
from scipy.spatial.distance import pdist, squareform

from evospaice.tree.centroid import (
    BUTTERFLY_FAMILIES,
    Dataset,
    distance_metrics,
    graft_nj,
    load_embeddings,
    sha256,
    tree_pair_distances,
)
from evospaice.validate.compare import (
    leaf_labels,
    load_tree,
    prepare_trees,
    retain_labels,
    topology_metrics,
)

METHODS = {
    "centroid": {
        "label": "Simple centroid", "units": "Cosine dissimilarity",
        "description": "Arithmetic mean of raw stored vectors; cosine distances connect species.",
    },
    "medoid": {
        "label": "Medoid", "units": "Cosine dissimilarity",
        "description": "The real record with the smallest total within-species cosine distance.",
    },
    "weighted": {
        "label": "GSC-weighted centroid", "units": "Cosine dissimilarity",
        "description": "Each leaf receives the sum of edge length / descendant count on its "
                       "midpoint-rooted NJ path. Normalized weights average the raw vectors.",
    },
    "wasserstein": {
        "label": "Gaussian / Wasserstein", "units": "W2 in raw vector units",
        "description": "A mean and unbiased sample covariance per species. Exact Gaussian W2 "
                       "distances use low-rank factors; singletons have zero covariance. "
                       "Local leaves use Euclidean distance, the W2 distance between point masses.",
    },
    "frechet": {
        "label": "Spherical Frechet mean", "units": "Cosine dissimilarity",
        "description": "An intrinsic mean minimizing squared angular distances on the unit sphere. "
                       "Cosine connectors keep the point-representation comparison consistent.",
    },
}


def gsc_weights(root: Clade, ids: list[str]) -> tuple[np.ndarray, bool]:
    counts = {}
    for node in root.find_clades(order="postorder"):
        counts[node] = 1 if node.is_terminal() else sum(counts[child] for child in node.clades)
    values = {}
    stack = [(root, 0.0)]
    while stack:
        node, weight = stack.pop()
        if node.is_terminal():
            values[node.name] = weight
        else:
            stack.extend(
                (child, weight + (child.branch_length or 0.0) / counts[child])
                for child in node.clades
            )
    weights = np.array([values[identifier] for identifier in ids])
    if np.any(weights < 0):
        raise ValueError("GSC weights require nonnegative branch lengths")
    zero_total = float(weights.sum()) == 0
    if zero_total:
        weights = np.ones(len(ids))
    return weights / weights.sum(), zero_total


def spherical_mean(vectors: np.ndarray, tolerance: float = 1e-10) -> tuple[np.ndarray, int]:
    unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    point = unit.mean(axis=0)
    if np.linalg.norm(point) < 1e-12:
        raise ValueError("The spherical mean has no stable initialization (antipodal data)")
    point /= np.linalg.norm(point)
    for iteration in range(256):
        cosine = np.clip(unit @ point, -1, 1)
        angles = np.arccos(cosine)
        if np.any(angles > np.pi - 1e-7):
            raise ValueError("The spherical logarithm is ambiguous at an antipodal point")
        ratios = np.ones_like(angles)
        nonzero = angles > 1e-8
        ratios[nonzero] = angles[nonzero] / np.sin(angles[nonzero])
        direction = ((unit - cosine[:, None] * point) * ratios[:, None]).mean(axis=0)
        direction -= (direction @ point) * point
        norm = np.linalg.norm(direction)
        if norm < tolerance:
            return point, iteration
        objective = float(np.mean(angles**2))
        step = 1.0
        for _ in range(40):
            candidate = np.cos(step * norm) * point + np.sin(step * norm) * direction / norm
            candidate /= np.linalg.norm(candidate)
            candidate_objective = float(np.mean(np.arccos(np.clip(unit @ candidate, -1, 1))**2))
            if candidate_objective <= objective - 1e-4 * step * norm**2:
                point = candidate
                break
            # Near floating-point precision, accept only a numerically stationary step.
            if abs(candidate_objective - objective) < 1e-14 and step * norm < 1e-8:
                return candidate, iteration + 1
            step /= 2
        else:
            raise RuntimeError("Spherical-mean line search failed to decrease its objective")
    raise RuntimeError("Spherical mean did not converge in 256 iterations")


def gaussian(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center = vectors.mean(axis=0)
    factor = (
        (vectors - center).T / np.sqrt(len(vectors) - 1)
        if len(vectors) > 1 else np.empty((vectors.shape[1], 0))
    )
    return center, factor


def gaussian_w2(first: tuple, second: tuple) -> float:
    first_mean, first_factor = first
    second_mean, second_factor = second
    trace = float(np.sum(first_factor**2) + np.sum(second_factor**2))
    cross = first_factor.T @ second_factor
    nuclear = float(np.linalg.svd(cross, compute_uv=False).sum()) if cross.size else 0.0
    covariance = trace - 2 * nuclear
    if covariance < -1e-9 * max(1.0, trace):
        raise ValueError("Gaussian covariance distance became negative beyond roundoff")
    return float(np.sqrt(np.sum((first_mean - second_mean)**2) + max(0.0, covariance)))


def build_genus(data: Dataset, method: str) -> tuple[Tree, dict]:
    if method not in METHODS:
        raise ValueError(f"Unknown representation: {method}")
    genera = set(data.taxonomy[:, 2])
    if len(genera) != 1:
        raise ValueError("Comparison requires exactly one genus")
    groups: dict[str, list[int]] = {}
    for index, species in enumerate(data.taxonomy[:, 3]):
        groups.setdefault(str(species), []).append(index)
    diagnostics: Counter = Counter()
    roots, representatives = [], []
    for species, indices in sorted(groups.items()):
        vectors = data.embeddings[indices]
        ids = list(map(str, data.ids[indices]))
        metric = "euclidean" if method == "wasserstein" else "cosine"
        local = np.maximum(pdist(vectors, metric=metric), 0)
        root = graft_nj(
            f"species:{species}", [Clade(name=identifier) for identifier in ids],
            local, diagnostics,
        )
        roots.append(root)
        if method == "centroid":
            representative = vectors.mean(axis=0)
        elif method == "medoid":
            representative = vectors[np.argmin(squareform(local).sum(axis=1))]
        elif method == "weighted":
            weights, zero = gsc_weights(root, ids)
            if zero and len(ids) > 1:
                diagnostics["gsc_uniform_zero_length_groups"] += 1
            representative = weights @ vectors
        elif method == "frechet":
            representative, iterations = spherical_mean(vectors)
            diagnostics["frechet_max_iterations"] = max(
                diagnostics["frechet_max_iterations"], iterations
            )
        else:
            representative = gaussian(vectors)
        representatives.append(representative)
    if method == "wasserstein":
        distances = np.array([gaussian_w2(a, b) for a, b in combinations(representatives, 2)])
    else:
        vectors = np.array(representatives)
        if np.any(np.linalg.norm(vectors, axis=1) == 0):
            raise ValueError(f"{method} produced a zero representative")
        distances = np.clip(pdist(vectors, metric="cosine"), 0, 2)
    root = graft_nj(f"genus:{next(iter(genera))}", roots, distances, diagnostics)
    return Tree(root=root, rooted=True), dict(diagnostics)


def encode_tree(tree) -> dict:
    nodes = list(tree.postorder_node_iter())
    indices = {node: i for i, node in enumerate(nodes)}
    all_ids = leaf_labels(tree)
    descendants = {}
    distance, depth = {}, {}
    for node in tree.preorder_node_iter():
        parent = node.parent_node
        distance[node] = (
            distance[parent] + (node.edge_length or 0.0) if parent is not None else 0.0
        )
        depth[node] = depth[parent] + 1 if parent is not None else 0
    result = []
    for node in nodes:
        tips = (
            {node.taxon.label} if node.is_leaf()
            else set().union(*(descendants[child] for child in node.child_node_iter()))
        )
        descendants[node] = tips
        split = None
        if 1 < len(tips) < len(all_ids) - 1:
            split = json.dumps(min(sorted(tips), sorted(all_ids - tips)), separators=(",", ":"))
        result.append({
            "id": indices[node], "children": [indices[c] for c in node.child_node_iter()],
            "label": node.taxon.label if node.is_leaf() else (node.label or ""),
            "leaf": node.is_leaf(), "distance": distance[node], "depth": depth[node],
            "length": node.edge_length or 0.0, "split": split,
        })
    return {"root": indices[tree.seed_node], "nodes": result}


def compare(
    embeddings: Path, metadata: Path, reference: Path, genus: str, output: Path,
) -> dict:
    if output.exists():
        raise FileExistsError(f"{output} already exists; choose a new output directory")
    with metadata.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not {"id", "genus", "species"} <= set(reader.fieldnames or ()):
            raise ValueError("Metadata must contain id, genus and species")
        rows = [row for row in reader if row["genus"] == genus]
    wanted = {row["id"] for row in rows}
    if len(wanted) != len(rows):
        raise ValueError("The requested metadata cohort contains duplicate IDs")
    data = load_embeddings(embeddings, BUTTERFLY_FAMILIES, wanted)
    if set(data.ids) != wanted or set(data.taxonomy[:, 2]) != {genus}:
        raise ValueError("The embeddings do not exactly match the requested genus cohort")
    species_lookup = dict(zip(map(str, data.ids), map(str, data.taxonomy[:, 3]), strict=True))
    if any(species_lookup[row["id"]] != row["species"] for row in rows):
        raise ValueError("Species metadata differs from the embedding bundle")
    reference_tree = load_tree(reference)
    if not wanted <= leaf_labels(reference_tree):
        raise ValueError("Reference tree does not contain every requested record ID")
    retain_labels(reference_tree, wanted)
    output.mkdir(parents=True)
    trees = {}
    diagnostics = {}
    for method in METHODS:
        tree, diagnostics[method] = build_genus(data, method)
        Phylo.write(tree, output / f"{method}.nwk", "newick", format_branch_length="%1.12g")
        trees[method] = load_tree(output / f"{method}.nwk")
    reference_tree.write(path=str(output / "reference.nwk"), schema="newick")
    trees["reference"] = reference_tree
    prepared, _ = prepare_trees(trees, mode="unrooted")
    pairwise_rf = {
        left: {
            right: topology_metrics(prepared[left], prepared[right])[0]
            for right in trees
        } for left in trees
    }
    pairs = list(combinations(range(len(data.ids)), 2))
    cosine = np.clip(pdist(data.embeddings, metric="cosine"), 0, 2)
    euclidean = pdist(data.embeddings, metric="euclidean")
    paths = {name: tree_pair_distances(tree, data.ids, pairs) for name, tree in trees.items()}
    summaries = {}
    for name in trees:
        common = distance_metrics(cosine, paths[name])
        denominator = float(paths[name] @ paths[name])
        if denominator <= 0:
            raise ValueError(f"{name} has no positive path distances to compare")
        scale = max(0.0, float(cosine @ paths[name] / denominator))
        entry = {
            **(METHODS[name] if name in METHODS else {
                "label": "Bactria reference", "units": "Reference sequence-distance units",
                "description": (
                    "Independent sequence-based reference, pruned to the same record IDs."
                ),
            }),
            "rf_to_centroid": pairwise_rf[name]["centroid"],
            "rf_to_reference": pairwise_rf[name]["reference"],
            "cosine_comparison": common,
            "reference_path_pearson": distance_metrics(paths["reference"], paths[name])["pearson"],
            "fitted_scale_to_cosine": scale,
            "scale_adjusted_stress": distance_metrics(cosine, paths[name] * scale)[
                "normalized_stress"
            ],
            "diagnostics": diagnostics.get(name),
        }
        if name != "reference":
            native = euclidean if name == "wasserstein" else cosine
            entry["native_distance_comparison"] = distance_metrics(native, paths[name])
        summaries[name] = entry
    payload = {
        "genus": genus, "records": len(data.ids), "species": len(set(data.taxonomy[:, 3])),
        "dimensions": data.embeddings.shape[1], "pairs": len(pairs),
        "speciesById": species_lookup, "methods": summaries,
        "trees": {name: encode_tree(tree) for name, tree in trees.items()},
        "pairwiseRF": pairwise_rf,
        "provenance": {
            "embeddings": str(embeddings), "sha256": sha256(embeddings),
            "cohort_metadata": str(metadata), "reference": str(reference),
            "evaluation": "All selected pairs are descriptive, not held-out validation",
            "scale_adjustment": "One nonnegative scale fitted and evaluated on the same pairs; "
                                "not biological calibration",
            "geometry": "Point methods use cosine at all stages; W2 uses raw Euclidean geometry "
                        "at leaves and Gaussian W2 at species connectors",
            "local_trees": "Recomputed per method; identical cosine inputs for point methods, "
                           "Euclidean inputs for W2",
        },
    }
    (output / "comparison.json").write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
    template = Path(__file__).parents[1] / "viz" / "tree_comparison.html"
    serialized = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    (output / "index.html").write_text(
        template.read_text().replace("/* COMPARISON_DATA */ null", serialized)
    )
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--genus", default="Papilio")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    payload = compare(args.embeddings, args.metadata, args.reference, args.genus, args.output_dir)
    print(f"{payload['genus']}: {payload['records']} records, {payload['species']} species")
    for name, entry in payload["methods"].items():
        print(
            f"{name}: RF vs centroid={entry['rf_to_centroid']['rf']}, "
            f"RF vs reference={entry['rf_to_reference']['rf']}, "
            f"cosine Spearman={entry['cosine_comparison']['spearman']:.4f}"
        )
    print(f"Comparison: {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
