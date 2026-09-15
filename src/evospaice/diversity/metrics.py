"""Phylogenetic alpha- and beta-diversity metrics."""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Literal, cast

import dendropy
import numpy as np
from skbio import TreeNode
from skbio.diversity import alpha_diversity, beta_diversity
from skbio.diversity.alpha import faith_pd as skbio_pd
from skbio.diversity.beta import unweighted_unifrac as skbio_unweighted
from skbio.diversity.beta import weighted_unifrac as skbio_weighted

Sample = Mapping[str, float]
Tree = dendropy.Tree | TreeNode
Backend = Literal["skbio", "unifrac"]


def faith_pd(tree: Tree, sample: Sample) -> float:
    """Return rooted Faith PD, excluding the incoming root stem."""
    prepared = prepare_tree(tree)
    taxa, counts = aligned_counts(prepared, [sample])
    return float(skbio_pd(counts[0] > 0, taxa, prepared, validate=False))


def unweighted_unifrac(
    tree: Tree,
    sample_a: Sample,
    sample_b: Sample,
    *,
    backend: Backend = "skbio",
) -> float:
    """Return presence/absence UniFrac; reject a zero-length branch union."""
    _check_backend(backend)
    prepared = prepare_tree(tree)
    taxa, counts = aligned_counts(prepared, [sample_a, sample_b])
    if skbio_pd(np.any(counts > 0, axis=0), taxa, prepared, validate=False) == 0:
        raise ValueError("UniFrac is undefined when neither sample spans a branch")
    if backend == "unifrac":
        return float(native_backend().unweighted_dense_pair(taxa, *counts, prepared))
    return float(skbio_unweighted(counts[0] > 0, counts[1] > 0, taxa, prepared, validate=False))


def weighted_unifrac(
    tree: Tree,
    sample_a: Sample,
    sample_b: Sample,
    *,
    backend: Backend = "skbio",
) -> float:
    """Return normalized weighted UniFrac with positive finite sample totals."""
    _check_backend(backend)
    prepared = prepare_tree(tree)
    taxa, counts = aligned_counts(prepared, [sample_a, sample_b])
    _check_totals(counts)
    if skbio_pd(np.any(counts > 0, axis=0), taxa, prepared, validate=False) == 0:
        raise ValueError("Weighted UniFrac is undefined when samples span no branches")
    if backend == "unifrac":
        return float(native_backend().weighted_normalized_dense_pair(taxa, *counts, prepared))
    integers = _integer_counts(counts)
    return float(skbio_weighted(
        integers[0], integers[1], taxa, prepared, normalized=True, validate=False
    ))


def _integer_counts(counts: np.ndarray) -> np.ndarray:
    """Preserve exact decimal ratios through scikit-bio's integer node accumulator."""
    result = np.zeros(counts.shape, dtype=np.int64)
    for index, row in enumerate(counts):
        ratios = [Fraction(str(value)) for value in row]
        denominator = math.lcm(*(value.denominator for value in ratios))
        integers = [value.numerator * (denominator // value.denominator) for value in ratios]
        divisor = math.gcd(*integers) or 1
        integers = [value // divisor for value in integers]
        if sum(integers) > 2**53:
            raise ValueError(
                "Abundance ratios exceed scikit-bio's exact integer range; use --backend unifrac"
            )
        result[index] = integers
    return result


def _check_totals(counts: np.ndarray) -> None:
    with np.errstate(over="ignore"):
        totals = counts.sum(axis=1)
    if not np.all(np.isfinite(totals) & (totals > 0)):
        raise ValueError("Weighted UniFrac requires a positive finite sample total")


def prepare_tree(tree: Tree) -> TreeNode:
    """Copy a rooted study tree without its incoming stem and validate all edges."""
    if isinstance(tree, dendropy.Tree):
        if tree.is_rooted is False:
            raise ValueError("Diversity requires a rooted study tree")
        copies = {}
        for node in tree.postorder_node_iter():
            name = node.taxon.label if node.taxon is not None else node.label
            copies[node] = TreeNode(
                name=name,
                length=0.0 if node is tree.seed_node else node.edge_length,
                children=[copies[child] for child in node.child_node_iter()],
            )
        result = copies[tree.seed_node]
    else:
        result = tree.copy()
        result.length = 0.0
    labels = []
    for node in result.preorder():
        if node.is_tip():
            if not isinstance(node.name, str) or not node.name.strip():
                raise ValueError("Every tree leaf must have a taxon label")
            labels.append(node.name)
        if node.length is None:
            raise ValueError(f"Branch leading to {node.name or '<internal node>'!r} has no length")
        if not math.isfinite(node.length) or node.length < 0:
            raise ValueError("Tree branch lengths must be finite and non-negative")
    if len(labels) != len(set(labels)):
        raise ValueError("Tree leaf labels must be unique")
    return result


def aligned_counts(tree: TreeNode, samples: Sequence[Sample]) -> tuple[list[str], np.ndarray]:
    """Align finite float abundances to exact tip IDs, including zero-count entries."""
    taxa = [cast(str, tree.name)] if tree.is_tip() else sorted(
        cast(str, node.name) for node in tree.tips()
    )
    positions = {taxon: index for index, taxon in enumerate(taxa)}
    counts = np.zeros((len(samples), len(taxa)), dtype=np.float64)
    for index, sample in enumerate(samples):
        unknown = set(sample) - positions.keys()
        if unknown:
            labels = ", ".join(sorted(unknown))
            raise ValueError(f"Sample contains taxa absent from the tree: {labels}")
        for taxon, abundance in sample.items():
            value = float(abundance)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"Abundance for {taxon!r} must be finite and non-negative")
            counts[index, positions[taxon]] = value
    return taxa, counts


def native_backend():
    """Load native UniFrac only on request, without implicit fallback."""
    try:
        return importlib.import_module("unifrac")
    except (ImportError, OSError) as error:
        raise ValueError(
            "UniFrac backend unavailable: install the fast-diversity extra and libssu "
            "(see diversity/README.md), or select --backend skbio"
        ) from error


def _check_backend(backend: str) -> None:
    if backend not in {"skbio", "unifrac"}:
        raise ValueError(f"Unknown diversity backend: {backend}")


def batch_diversity(
    tree: Tree,
    samples: Mapping[str, Sample],
    *,
    backend: Backend = "skbio",
    memory_mb: float = 512,
) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Prepare once and delegate batch mathematics to public library drivers.

    Project validation replaces library rooting heuristics so explicitly rooted
    multifurcations are accepted without inventing resolutions.
    """
    _check_backend(backend)
    if not math.isfinite(memory_mb) or memory_mb <= 0:
        raise ValueError("memory_mb must be positive and finite")
    sample_ids = sorted(samples)
    if not sample_ids:
        raise ValueError("Sample table contains no observations")
    prepared = prepare_tree(tree)
    size = len(sample_ids)
    estimate = 8 * (4 * size * prepared.count() + 4 * size * size)
    if estimate > memory_mb * 1024**2:
        raise ValueError(
            "Diversity memory budget exceeded; reduce samples/tree or raise --memory-mb"
        )
    taxa, counts = aligned_counts(prepared, [samples[name] for name in sample_ids])
    alpha = alpha_diversity(
        "faith_pd", counts > 0, ids=sample_ids, taxa=taxa, tree=prepared, validate=False
    ).to_numpy()
    empty = np.zeros((size, size))
    native = native_backend() if backend == "unifrac" else None
    if size < 2:
        return sample_ids, alpha, empty, empty.copy()
    _check_totals(counts)
    if np.count_nonzero(alpha == 0) > 1:
        raise ValueError("UniFrac is undefined when samples span no branches")
    if native is not None:
        from biom import Table

        table = Table(counts.T, observation_ids=taxa, sample_ids=sample_ids)
        unweighted = native.unweighted_fp64(table, prepared).filter(sample_ids).data
        weighted = native.weighted_normalized_fp64(table, prepared).filter(sample_ids).data
    else:
        unweighted = beta_diversity(
            "unweighted_unifrac", counts > 0, ids=sample_ids,
            taxa=taxa, tree=prepared, validate=False,
        ).data
        weighted = beta_diversity(
            "weighted_unifrac", _integer_counts(counts), normalized=True,
            ids=sample_ids, taxa=taxa, tree=prepared, validate=False,
        ).data
    if not np.isfinite(unweighted).all() or not np.isfinite(weighted).all():
        raise ValueError("UniFrac returned non-finite distances")
    return sample_ids, alpha, unweighted, weighted
