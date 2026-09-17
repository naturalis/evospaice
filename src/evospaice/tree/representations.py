"""Descendant representations shared by full-hierarchy builds and genus comparisons."""

from __future__ import annotations

from collections import Counter
from itertools import combinations

import numpy as np
from Bio.Phylo.BaseTree import Clade
from scipy.spatial.distance import pdist

Representation = np.ndarray | tuple[np.ndarray, np.ndarray]

METHODS = {
    "centroid": {
        "label": "Simple centroid", "units": "Cosine dissimilarity",
        "description": "Arithmetic mean of all raw stored descendant vectors.",
        "propagation": "child centroids weighted by their descendant record counts",
        "distance": "cosine",
    },
    "medoid": {
        "label": "Medoid", "units": "Cosine dissimilarity",
        "description": "Actual descendant record minimizing total descendant cosine distance.",
        "propagation": "exact search over all descendant records, not child medoids; "
                       "cosine totals via n - unit_vector dot sum_of_unit_vectors; "
                       "first input record wins numerical ties",
        "distance": "cosine",
    },
    "weighted": {
        "label": "GSC-weighted centroid", "units": "Cosine dissimilarity",
        "description": "Raw descendant vectors averaged with full-subtree GSC leaf weights.",
        "propagation": "recompute weights on the complete grafted descendant subtree: "
                       "sum edge length / descendant count along each root-to-leaf path; "
                       "normalize; use uniform weights for zero total length",
        "distance": "cosine",
    },
    "wasserstein": {
        "label": "Gaussian / Wasserstein", "units": "W2 in raw vector units",
        "description": "Raw descendant sample mean and unbiased sample covariance, "
                       "including between-child variance; singletons have zero covariance.",
        "propagation": "refit all raw descendants; exact covariance factors compressed "
                       "to at most the embedding dimension, without regularization",
        "distance": "Gaussian W2; Euclidean between record point masses",
    },
    "frechet": {
        "label": "Spherical Frechet mean", "units": "Cosine dissimilarity",
        "description": "Intrinsic spherical mean fitted over all normalized descendant vectors.",
        "propagation": "Riemannian descent on descendant squared angular distances, "
                       "not child means; deterministic extrinsic initialization, "
                       "256 iterations maximum; no general global-minimum guarantee; "
                       "antipodal ambiguity and nonconvergence are errors",
        "distance": "cosine (squared angular distance is only the fitting objective)",
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
    if not np.isfinite(weights).all() or np.any(weights < 0):
        raise ValueError("GSC weights require finite nonnegative branch lengths")
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
            if abs(candidate_objective - objective) < 1e-14 and step * norm < 1e-8:
                return candidate, iteration + 1
            step /= 2
        else:
            raise RuntimeError("Spherical-mean line search failed to decrease its objective")
    raise RuntimeError("Spherical mean did not converge in 256 iterations")


def cosine_medoid(vectors: np.ndarray) -> np.ndarray:
    """Exact cosine objective over every record in O(n*d), with no pairwise matrix."""
    unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    scores = unit @ unit.sum(axis=0)
    # Preserve input-order tie breaking despite dot-product roundoff.
    tolerance = 16 * np.finfo(float).eps * len(vectors)
    index = np.flatnonzero(scores >= scores.max() - tolerance)[0]
    return vectors[index]


def gaussian(vectors: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center = vectors.mean(axis=0)
    factor = (
        (vectors - center).T / np.sqrt(len(vectors) - 1)
        if len(vectors) > 1 else np.empty((vectors.shape[1], 0))
    )
    if factor.shape[1] > factor.shape[0]:
        # A = R.T has A A.T = factor factor.T; no rank truncation or ridge.
        factor = np.linalg.qr(factor.T, mode="r").T
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


def represent(
    vectors: np.ndarray, ids: list[str], root: Clade, method: str, diagnostics: Counter,
) -> Representation:
    """Fit a taxon's representation to its records, never equally to child summaries."""
    if method not in METHODS:
        raise ValueError(f"Unknown representation: {method}")
    if method == "wasserstein":
        return gaussian(vectors)
    if method == "centroid":
        point = vectors.mean(axis=0)
    elif method == "medoid":
        point = cosine_medoid(vectors)
    elif method == "weighted":
        weights, zero = gsc_weights(root, ids)
        if zero and len(ids) > 1:
            diagnostics["gsc_uniform_zero_length_groups"] += 1
        point = weights @ vectors
    else:
        point, iterations = spherical_mean(vectors)
        diagnostics["frechet_max_iterations"] = max(
            diagnostics["frechet_max_iterations"], iterations
        )
    if not np.isfinite(point).all() or np.linalg.norm(point) == 0:
        raise ValueError(f"{method} produced a zero or non-finite representative")
    return point


def representative_distances(representatives: list[Representation], method: str) -> np.ndarray:
    if method not in METHODS:
        raise ValueError(f"Unknown representation: {method}")
    if method == "wasserstein":
        return np.array([gaussian_w2(a, b) for a, b in combinations(representatives, 2)])
    return np.clip(pdist(np.array(representatives), metric="cosine"), 0, 2)
