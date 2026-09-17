"""Indexed path, taxonomy, and sampled metric calculations without all-pairs matrices."""

from __future__ import annotations

import math
from collections import defaultdict

import dendropy
import numpy as np

from evospaice.tree.centroid import RANKS, distance_metrics

from .compare import leaf_labels


class TreeIndex:
    """Preorder indices and binary lifting for vectorized MRCA queries."""

    def __init__(self, tree: dendropy.Tree, *, lengths: bool = True):
        leaf_labels(tree)
        nodes = list(tree.preorder_node_iter())
        lookup = {node: i for i, node in enumerate(nodes)}
        size = len(nodes)
        parents = np.zeros(size, dtype=np.int64)
        self.depth = np.zeros(size, dtype=np.int64)
        self.distance = np.zeros(size)
        self.descendant_tips = np.zeros(size, dtype=np.int64)
        self.tips: dict[str, int] = {}
        for i, node in enumerate(nodes):
            if i:
                parent = lookup[node.parent_node]
                parents[i] = parent
                self.depth[i] = self.depth[parent] + 1
                length = node.edge_length if lengths else 0.0
                if length is None or not math.isfinite(length) or length < 0:
                    raise ValueError("Path metrics require finite, nonnegative non-root lengths")
                self.distance[i] = self.distance[parent] + length
                if not math.isfinite(self.distance[i]):
                    raise ValueError("Root-to-node distances overflowed")
            if node.is_leaf():
                self.tips[node.taxon.label] = i
                self.descendant_tips[i] = 1
        for i in range(size - 1, 0, -1):
            self.descendant_tips[parents[i]] += self.descendant_tips[i]
        levels = max(1, int(self.depth.max()).bit_length())
        self.up = np.empty((levels, size), dtype=np.int64)
        self.up[0] = parents
        for level in range(1, levels):
            self.up[level] = self.up[level - 1, self.up[level - 1]]

    def leaves(self, labels: list[str]) -> np.ndarray:
        return np.array([self.tips[label] for label in labels], dtype=np.int64)

    def lca(self, first: np.ndarray, second: np.ndarray) -> np.ndarray:
        first, second = np.broadcast_arrays(first, second)
        swap = self.depth[first] < self.depth[second]
        a, b = np.where(swap, second, first), np.where(swap, first, second)
        difference = self.depth[a] - self.depth[b]
        for level in range(len(self.up)):
            a = np.where((difference >> level) & 1, self.up[level, a], a)
        for level in range(len(self.up) - 1, -1, -1):
            next_a, next_b = self.up[level, a], self.up[level, b]
            move = next_a != next_b
            a, b = np.where(move, next_a, a), np.where(move, next_b, b)
        return np.where(a == b, a, self.up[0, a])

    def paths(self, first: np.ndarray, second: np.ndarray) -> np.ndarray:
        ancestor = self.lca(first, second)
        result = ((self.distance[first] - self.distance[ancestor])
                  + (self.distance[second] - self.distance[ancestor]))
        if not np.isfinite(result).all():
            raise ValueError("Pairwise path distances overflowed")
        return result


def errors(target: np.ndarray, predicted: np.ndarray) -> dict:
    """Squared review stress, path correlations, MAE, and zero-aware MAPE."""
    if target.ndim != 1 or target.shape != predicted.shape or not len(target):
        raise ValueError("Distance vectors must be matching, nonempty one-dimensional arrays")
    if (not np.isfinite(target).all() or not np.isfinite(predicted).all()
            or np.any(target < 0) or np.any(predicted < 0)):
        raise ValueError("Distances must be finite and nonnegative")
    absolute = np.abs(predicted - target)
    positive = target > 0
    baseline = distance_metrics(target, predicted) if positive.any() else {
        "pairs": len(target), "normalized_stress": None, "pearson": None, "spearman": None,
        "mean_signed_error": float((predicted - target).mean()),
        "p90_absolute_error": float(np.quantile(absolute, .9)),
    }
    return {
        **baseline,
        "stress_squared": (
            baseline["normalized_stress"] ** 2 if baseline["normalized_stress"] is not None
            else None
        ),
        "mae": float(absolute.mean()),
        "mape_percent": float((absolute[positive] / target[positive]).mean() * 100)
        if positive.any() else None,
        "mape_zero_targets_excluded": int((~positive).sum()),
        "undefined": {
            "stress": "all target distances are zero" if not positive.any() else None,
            "correlations": "constant distance vector" if baseline["pearson"] is None else None,
        },
    }


def fitted_errors(target: np.ndarray, predicted: np.ndarray) -> dict:
    denominator = float(predicted @ predicted)
    numerator = float(target @ predicted)
    if not math.isfinite(denominator) or not math.isfinite(numerator):
        raise ValueError("Scalar-alignment sums overflowed")
    if denominator == 0:
        return {"status": "undefined", "reason": "all predicted distances are zero"}
    scale = max(0.0, numerator / denominator)
    return {
        "status": "computed", "scale": scale, "metrics": errors(target, predicted * scale),
        "scope": "one nonnegative scalar fitted and evaluated on the same sampled pairs",
    }


def kc_topology(first: np.ndarray, second: np.ndarray, leaves: int) -> dict:
    """Estimate lambda=0 KC using root-to-MRCA edge counts and n unit pendant entries."""
    if first.shape != second.shape or first.ndim != 1 or not len(first) or leaves < 2:
        raise ValueError("KC requires matching sampled MRCA vectors and at least two tips")
    total = leaves * (leaves - 1) // 2
    if len(first) > total:
        raise ValueError("KC sample exceeds the number of possible leaf pairs")
    first, second = first.astype(float), second.astype(float)
    factor = total / len(first)
    squared = float((first - second) @ (first - second)) * factor
    norm_first = math.sqrt(float(first @ first) * factor + leaves)
    norm_second = math.sqrt(float(second @ second) * factor + leaves)
    distance = math.sqrt(squared)
    return {
        "lambda": 0, "distance": distance, "normalized": distance / (norm_first + norm_second),
        "normalization": "Euclidean difference / sum of the two full vector norms; explicit "
                         "bounded convention, not a uniquely standardized KC normalization",
        "exact": len(first) == total, "sampled_pairs": len(first), "possible_pairs": total,
        "estimation": "uniform-pair sum-of-squares expansion plus all unit pendant entries; "
                      "square-root distance and normalized ratio are plug-in estimates",
        "vector_definition": "pair entries count root-to-MRCA edges; pendant entries equal one",
    }


def taxon_purity(
    indices: dict[str, TreeIndex], labels: list[str], taxonomy: np.ndarray,
) -> tuple[dict, list[dict]]:
    if taxonomy.shape != (len(labels), len(RANKS)):
        raise ValueError("Taxonomy must align with every evaluated record")
    tips = {name: index.leaves(labels) for name, index in indices.items()}
    summaries, rows = {}, []
    for depth, rank in enumerate(RANKS):
        groups: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for i, row in enumerate(taxonomy):
            groups[tuple(map(str, row[:depth + 1]))].append(i)
        groups = dict(sorted(groups.items()))
        counts = np.array([len(members) for members in groups.values()])
        nontrivial = counts > 1
        per_tree = {}
        for name, index in indices.items():
            # MRCA of the first and last preorder members is the MRCA of the entire group.
            low = np.array([tips[name][members].min() for members in groups.values()])
            high = np.array([tips[name][members].max() for members in groups.values()])
            sizes = index.descendant_tips[index.lca(low, high)]
            purity = counts / sizes
            per_tree[name] = (sizes, purity)
            summaries.setdefault(rank, {})[name] = {
                "taxa": len(groups), "singleton_taxa": int((~nontrivial).sum()),
                "nontrivial_taxa": int(nontrivial.sum()),
                "macro_purity_all": float(purity.mean()),
                "macro_purity_nontrivial": float(purity[nontrivial].mean())
                if nontrivial.any() else None,
                "monophyletic_nontrivial": int((counts[nontrivial] == sizes[nontrivial]).sum()),
                "monophyletic_fraction_nontrivial": float(
                    (counts[nontrivial] == sizes[nontrivial]).mean()
                ) if nontrivial.any() else None,
            }
        for i, lineage in enumerate(groups):
            row = {"rank": rank, "taxon": lineage[-1], "lineage": " > ".join(lineage),
                   "records": int(counts[i])}
            for name, (sizes, purity) in per_tree.items():
                row[f"{name}_mrca_tips"] = int(sizes[i])
                row[f"{name}_purity"] = float(purity[i])
            rows.append(row)
    return summaries, rows


def neighbor_preservation(
    indices: dict[str, TreeIndex], labels: list[str], unit: np.ndarray,
    *, k: int, anchors: int, seed: int,
) -> tuple[dict, list[dict]]:
    count = len(labels)
    if not 1 <= k < count or anchors < 1:
        raise ValueError("k must be positive and smaller than the cohort; anchors must be positive")
    if labels != sorted(labels):
        raise ValueError("Neighbor candidates must be sorted for deterministic tie-breaking")
    chosen = np.sort(np.random.default_rng(seed).choice(count, min(anchors, count), replace=False))
    tips = {name: index.leaves(labels) for name, index in indices.items()}
    rows, overlap = [], {name: [] for name in indices}

    def nearest(distances: np.ndarray, anchor: int) -> np.ndarray:
        distances[anchor] = np.inf
        return np.argsort(distances, kind="stable")[:k]

    for anchor in chosen:
        embedding = nearest(np.clip(1 - unit @ unit[anchor], 0, 2), anchor)
        expected = set(map(int, embedding))
        row = {"anchor_id": labels[anchor], "k": k,
               "embedding_neighbors": [labels[i] for i in embedding]}
        for name, index in indices.items():
            neighbors = nearest(index.paths(tips[name][anchor], tips[name]), anchor)
            score = len(expected.intersection(map(int, neighbors))) / k
            overlap[name].append(score)
            row[f"{name}_overlap"] = score
            row[f"{name}_neighbors"] = [labels[i] for i in neighbors]
        rows.append(row)
    return {
        "k": k, "anchors": len(chosen), "candidate_tips": count, "seed": seed,
        "exact_neighborhoods": True, "all_anchors_evaluated": len(chosen) == count,
        "tie_breaking": "lexicographic record ID for exactly equal computed distances",
        "mean_precision_at_k": {name: float(np.mean(scores)) for name, scores in overlap.items()},
        "scope": "uniformly sampled anchors; each anchor searches every matched candidate",
    }, rows
