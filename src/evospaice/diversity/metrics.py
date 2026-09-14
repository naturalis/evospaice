"""Phylogenetic alpha- and beta-diversity metrics."""

from __future__ import annotations

import math
from collections.abc import Mapping

import dendropy

Sample = Mapping[str, float]


def faith_pd(tree: dendropy.Tree, sample: Sample) -> float:
    """Return rooted Faith's phylogenetic diversity for a sample.

    Every branch on a path from an observed tip to the root is counted once.
    Taxa with zero abundance are treated as absent.
    """
    masses = _branch_masses(tree, sample)
    return sum(_edge_length(node) for node, mass in masses.items() if mass > 0)


def unweighted_unifrac(
    tree: dendropy.Tree,
    sample_a: Sample,
    sample_b: Sample,
) -> float:
    """Return unweighted UniFrac distance between two samples."""
    masses_a = _branch_masses(tree, sample_a)
    masses_b = _branch_masses(tree, sample_b)

    unique = 0.0
    union = 0.0
    for node in masses_a:
        present_a = masses_a[node] > 0
        present_b = masses_b[node] > 0
        if not (present_a or present_b):
            continue
        length = _edge_length(node)
        union += length
        if present_a != present_b:
            unique += length

    if union == 0:
        raise ValueError("UniFrac is undefined when neither sample spans a branch")
    return unique / union


def weighted_unifrac(
    tree: dendropy.Tree,
    sample_a: Sample,
    sample_b: Sample,
) -> float:
    """Return normalized weighted UniFrac distance between two samples."""
    total_a = _sample_total(sample_a)
    total_b = _sample_total(sample_b)
    masses_a = _branch_masses(tree, sample_a)
    masses_b = _branch_masses(tree, sample_b)

    difference = 0.0
    combined = 0.0
    for node in masses_a:
        proportion_a = masses_a[node] / total_a
        proportion_b = masses_b[node] / total_b
        length = _edge_length(node)
        difference += length * abs(proportion_a - proportion_b)
        combined += length * (proportion_a + proportion_b)

    if combined == 0:
        raise ValueError("Weighted UniFrac is undefined when samples span no branches")
    return difference / combined


def _branch_masses(tree: dendropy.Tree, sample: Sample) -> dict[dendropy.Node, float]:
    abundances = _validated_abundances(tree, sample)
    masses: dict[dendropy.Node, float] = {}

    for node in tree.postorder_node_iter():
        if node is tree.seed_node:
            continue
        if node.is_leaf():
            masses[node] = abundances.get(node.taxon.label, 0.0)
        else:
            masses[node] = sum(masses[child] for child in node.child_node_iter())
        _edge_length(node)

    return masses


def _validated_abundances(tree: dendropy.Tree, sample: Sample) -> dict[str, float]:
    leaf_labels = [leaf.taxon.label for leaf in tree.leaf_node_iter()]
    if any(label is None for label in leaf_labels):
        raise ValueError("Every tree leaf must have a taxon label")
    if len(set(leaf_labels)) != len(leaf_labels):
        raise ValueError("Tree leaf labels must be unique")

    unknown = set(sample) - set(leaf_labels)
    if unknown:
        labels = ", ".join(sorted(unknown))
        raise ValueError(f"Sample contains taxa absent from the tree: {labels}")

    abundances: dict[str, float] = {}
    for label, abundance in sample.items():
        value = float(abundance)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Abundance for {label!r} must be finite and non-negative")
        abundances[label] = value
    return abundances


def _sample_total(sample: Sample) -> float:
    total = sum(float(abundance) for abundance in sample.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Weighted UniFrac requires a positive finite sample total")
    return total


def _edge_length(node: dendropy.Node) -> float:
    length = node.edge_length
    if length is None:
        label = node.taxon.label if node.taxon is not None else node.label
        raise ValueError(f"Branch leading to {label or '<internal node>'!r} has no length")
    value = float(length)
    if not math.isfinite(value) or value < 0:
        raise ValueError("Tree branch lengths must be finite and non-negative")
    return value
