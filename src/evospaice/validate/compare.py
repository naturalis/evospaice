"""Bounded, explicit comparisons of phylogenetic trees using DendroPy."""

from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
import random
from collections.abc import Mapping, Sequence
from pathlib import Path

import dendropy
import numpy as np
from dendropy.calculate import treecompare
from scipy.stats import pearsonr, spearmanr


def leaf_labels(tree: dendropy.Tree) -> set[str]:
    """Require unique, nonempty leaf labels without changing case or punctuation."""
    labels = [node.taxon.label if node.taxon else None for node in tree.leaf_node_iter()]
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("Every tree leaf must have a nonempty taxon label")
    if len(labels) != len(set(labels)):
        raise ValueError("Tree leaf labels must be unique")
    return set(labels)


class BoundedNamespace(dendropy.TaxonNamespace):
    """Reject excessive tip allocation while DendroPy parses Newick."""

    def __init__(self, maximum: int):
        super().__init__(is_case_sensitive=True)
        self.maximum = maximum

    def add_taxon(self, taxon):
        if taxon not in self and len(self) >= self.maximum:
            raise ValueError("Tree tip limit exceeded; provide a benchmark subset")
        return super().add_taxon(taxon)


def load_tree(
    path: Path, *, max_bytes: int = 32 * 1024**2, max_tips: int = 5000
) -> dendropy.Tree:
    """Read a single Newick with bounded decompressed size and tip allocation."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        content = handle.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("Tree input size limit exceeded; provide a benchmark clade subset")
    trees = dendropy.TreeList.get(
        data=content.decode("utf-8"), schema="newick", preserve_underscores=True,
        taxon_namespace=BoundedNamespace(max_tips),
        case_sensitive_taxon_labels=True, extract_comment_metadata=True,
    )
    if len(trees) != 1:
        raise ValueError("Each comparison input must contain exactly one tree")
    leaf_labels(trees[0])
    return trees[0]


def branch_qc(tree: dendropy.Tree) -> dict:
    """Summarize original non-root edges before path-suppressing operations."""
    counts = {"missing": 0, "nonfinite": 0, "negative": 0, "zero": 0}
    groups = {"terminal": [], "internal": []}
    for node in tree.preorder_node_iter():
        if node is tree.seed_node:
            continue
        value = node.edge_length
        if value is None:
            counts["missing"] += 1
        elif not math.isfinite(value):
            counts["nonfinite"] += 1
        elif value < 0:
            counts["negative"] += 1
        else:
            counts["zero"] += int(value == 0)
            groups["terminal" if node.is_leaf() else "internal"].append(value)
    valid = not any(counts[key] for key in ("missing", "nonfinite", "negative"))
    total = float(sum(map(sum, groups.values())))
    if not math.isfinite(total):
        valid = False
        counts["nonfinite"] += 1
    return {
        **counts, "valid": valid, "total": total if valid else None,
        **{name: {"count": len(values), "median": float(np.median(values)) if values else None}
           for name, values in groups.items()},
    }


def prepare_trees(
    trees: Mapping[str, dendropy.Tree], *, mode: str, taxa_policy: str = "strict",
    mappings: Mapping[str, Mapping[str, str]] | None = None,
    selected: set[str] | None = None, max_tips: int = 5000,
) -> tuple[dict[str, dendropy.Tree], list[dict], dict[str, dict]]:
    """Align copies to one canonical namespace and fixed benchmark set."""
    if not trees:
        raise ValueError("No trees supplied")
    if mode not in {"rooted", "unrooted"} or taxa_policy not in {"strict", "intersection"}:
        raise ValueError("Invalid rooting mode or taxa policy")
    if max_tips < 1:
        raise ValueError("max_tips must be positive")
    working, originals, sets, qc = {}, {}, {}, {}
    for name, tree in trees.items():
        labels = leaf_labels(tree)
        if len(labels) > max_tips:
            raise ValueError(f"{name}: tip limit exceeded; supply a subset or raise --max-tips")
        mapping = dict((mappings or {}).get(name, {}))
        if mapping.keys() - labels:
            raise ValueError(f"{name}: mapping contains labels absent from the tree")
        copy = tree.clone(depth=2)
        originals[name] = {}
        for node in copy.leaf_node_iter():
            original = node.taxon.label
            canonical = mapping.get(original, original)
            originals[name][original] = canonical
            node.taxon.label = canonical
        sets[name] = leaf_labels(copy)
        qc[name] = branch_qc(copy)
        copy.is_rooted = mode == "rooted"
        working[name] = copy
    restricted = {name: labels & selected if selected is not None else labels
                  for name, labels in sets.items()}
    if selected is not None and selected - set.union(*sets.values()):
        raise ValueError("Selected taxa include IDs absent from every tree")
    common = set.intersection(*restricted.values())
    if taxa_policy == "strict" and any(labels != common for labels in restricted.values()):
        raise ValueError("Tree taxa differ; supply a mapping or request --taxa-policy intersection")
    minimum = 3 if mode == "rooted" else 4
    if len(common) < minimum:
        raise ValueError(f"{mode} comparison requires at least {minimum} shared tips")
    namespace = dendropy.TaxonNamespace(sorted(common), is_case_sensitive=True)
    coverage = []
    for name, tree in working.items():
        for original, canonical in sorted(originals[name].items()):
            retained = canonical in common
            reason = "retained" if retained else (
                "not_selected"
                if selected is not None and canonical not in selected else "not_shared"
            )
            coverage.append(dict(tree=name, label=original, taxon=canonical,
                                 retained=retained, reason=reason))
        tree.retain_taxa_with_labels(common, suppress_unifurcations=False)
        for node in list(tree.postorder_node_iter()):
            if node is tree.seed_node or len(node.child_nodes()) != 1:
                continue
            child = node.child_nodes()[0]
            child.edge_length = (
                None if child.edge_length is None or node.edge_length is None
                else child.edge_length + node.edge_length
            )
            parent = node.parent_node
            node.remove_child(child)
            parent.remove_child(node)
            parent.add_child(child)
        tree.seed_node.edge_length = 0.0
        tree.migrate_taxon_namespace(namespace, unify_taxa_by_label=True)
        tree.encode_bipartitions(suppress_unifurcations=False)
    return working, coverage, qc


def support_view(
    tree: dendropy.Tree, *, field: str, scale: str, minimum: float | None = None
) -> tuple[dendropy.Tree, dict[str, float], int]:
    """Filter only topology: collapsing an edge cannot preserve all path lengths."""
    if scale not in {"fraction", "percent"}:
        raise ValueError("Support scale must be fraction or percent")
    if minimum is not None and (not math.isfinite(minimum) or not 0 <= minimum <= 1):
        raise ValueError("Minimum support must be a fraction in [0, 1]")
    copy = tree.clone(depth=1)
    copy.encode_bipartitions(suppress_unifurcations=False)
    values, collapsed = {}, 0
    for mask, node in list(informative_splits(copy).items()):
        raw = node.label if field == "label" else node.annotations.get_value(field)
        if raw is None:
            if minimum is not None:
                raise ValueError("Reference support is missing on an informative branch")
            continue
        value = float(raw) / (100 if scale == "percent" else 1)
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Support values must be within the declared scale")
        values[split_id(mask, copy)] = value
        if minimum is not None and value < minimum:
            node.edge.collapse()
            collapsed += 1
    copy.encode_bipartitions(suppress_unifurcations=False)
    return copy, values, collapsed


def informative_splits(tree: dendropy.Tree) -> dict[int, dendropy.Node]:
    """Return nontrivial rooted clades or canonical unrooted splits."""
    size = len(leaf_labels(tree))
    result = {}
    for node in tree.postorder_node_iter():
        mask = (node.bipartition.leafset_bitmask if tree.is_rooted
                else node.bipartition.split_bitmask)
        count = mask.bit_count()
        if 1 < count < size and (tree.is_rooted or size - count > 1):
            result[mask] = node
    return result


def split_id(mask: int, tree: dendropy.Tree) -> str:
    labels = [
        taxon.label for index, taxon in enumerate(tree.taxon_namespace) if mask & (1 << index)
    ]
    encoded = json.dumps(labels, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:20]


def _compatible(first: int, second: int, full: int, rooted: bool) -> bool:
    if rooted:
        return not first & second or first & second in {first, second}
    return any(part == 0 for part in (
        first & second, first & (full ^ second), (full ^ first) & second,
        (full ^ first) & (full ^ second),
    ))


def topology_metrics(inferred: dendropy.Tree, reference: dendropy.Tree) -> tuple[dict, list[dict]]:
    """Compute RF and exact agreement; distinguish unresolved from contradictory."""
    first, second = set(informative_splits(inferred)), set(informative_splits(reference))
    shared = len(first & second)
    denominator = len(first) + len(second)
    raw = treecompare.symmetric_difference(inferred, reference, is_bipartitions_updated=True)
    false_positive, false_negative = treecompare.false_positives_and_negatives(
        reference, inferred, is_bipartitions_updated=True
    )
    if raw != len(first ^ second) or raw != false_positive + false_negative:
        raise ValueError("DendroPy RF differs from informative split counts after normalization")
    if len(first | second) * max(len(first), len(second)) > 25_000_000:
        raise ValueError("Split compatibility work limit exceeded; use a smaller clade")
    full = (1 << len(inferred.taxon_namespace)) - 1
    rows = []
    for mask in sorted(first | second):
        origin = "both" if mask in first & second else "inferred" if mask in first else "reference"
        other = second if mask in first else first
        status = "shared" if origin == "both" else (
            "compatible_unresolved" if all(
                _compatible(mask, candidate, full, inferred.is_rooted) for candidate in other
            ) else "conflicting"
        )
        rows.append(dict(clade_id=split_id(mask, inferred), origin=origin,
                         size=mask.bit_count(), status=status))
    metrics = dict(
        kind="clade" if inferred.is_rooted else "split", rf=raw,
        rf_normalized=raw / denominator if denominator else None,
        rf_denominator=denominator, rf_normalization="observed_informative_splits",
        shared=shared, inferred_only=len(first - second), reference_only=len(second - first),
        inferred_count=len(first), reference_count=len(second),
        precision=shared / len(first) if first else None,
        recall=shared / len(second) if second else None,
        f1=2 * shared / denominator if denominator else None,
        undefined_reasons={
            **({"precision": "no_inferred_relationships"} if not first else {}),
            **({"recall": "no_reference_relationships"} if not second else {}),
            **({"rf_normalized": "no_resolved_relationships", "f1": "no_resolved_relationships"}
               if not denominator else {}),
        },
    )
    return metrics, rows


def sample_pairs(
    taxa: Sequence[str], max_pairs: int = 50_000, seed: int = 0
) -> list[tuple[str, str]]:
    """Sample unordered pair indices without allocating all possible pairs."""
    if max_pairs < 1:
        raise ValueError("max_pairs must be positive")
    labels = sorted(taxa)
    size = len(labels)
    total = size * (size - 1) // 2
    indices = range(total) if total <= max_pairs else sorted(random.Random(seed).sample(
        range(total), max_pairs
    ))
    starts = [index * (2 * size - index - 1) // 2 for index in range(size)]
    pairs = []
    for index in indices:
        first = bisect.bisect_right(starts, index) - 1
        second = first + 1 + index - starts[first]
        pairs.append((labels[first], labels[second]))
    return pairs


class PathDistances:
    """Answer selected patristic queries without an all-taxon distance matrix."""

    def __init__(self, tree: dendropy.Tree):
        if not tree.is_rooted:
            tree = tree.clone(depth=1)
            tree.is_rooted = True
            tree.encode_bipartitions(suppress_unifurcations=False)
        self.tree = tree
        self.nodes = {node.taxon.label: node for node in tree.leaf_node_iter()}
        self.depths = {tree.seed_node: 0.0}
        for node in tree.preorder_node_iter():
            if node is not tree.seed_node:
                self.depths[node] = self.depths[node.parent_node] + node.edge_length

    def distance(self, first: str, second: str) -> float:
        ancestor = self.tree.mrca(taxon_labels=[first, second], is_bipartitions_updated=True)
        return self.depths[self.nodes[first]] + self.depths[self.nodes[second]] - 2 * self.depths[
            ancestor
        ]


def distance_summary(first: Sequence[float], second: Sequence[float], *, errors: bool) -> dict:
    """Descriptive coefficients only: taxon pairs are not independent observations."""
    left, right = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if left.shape != right.shape or not np.isfinite(left).all() or not np.isfinite(right).all():
        raise ValueError("Distance vectors must match and be finite")
    informative = len(left) >= 2 and np.ptp(left) > 0 and np.ptp(right) > 0
    result = dict(
        count=len(left), pearson=float(pearsonr(left, right).statistic) if informative else None,
        spearman=float(spearmanr(left, right).statistic) if informative else None,
        correlation_reason=None if informative else "insufficient_or_constant_distances",
    )
    if errors and len(left):
        residual = left - right
        result.update(mae=float(np.mean(np.abs(residual))), rmse=float(np.sqrt(
            np.mean(residual**2))), bias=float(np.mean(residual)))
    return result


def branch_metrics(
    inferred: dendropy.Tree, reference: dendropy.Tree, pairs: list[tuple[str, str]],
    *, length_mode: str = "none", inferred_units: str | None = None,
    reference_units: str | None = None, units_evidence: str | None = None,
    original_qc: Mapping[str, dict] | None = None,
) -> tuple[dict, list[dict]]:
    """Compare valid paths and gate absolute edge errors on declared units."""
    if length_mode not in {"none", "raw", "total-length"}:
        raise ValueError("Unknown length mode")
    if length_mode == "raw" and (
        not inferred_units or inferred_units != reference_units or not units_evidence
    ):
        raise ValueError("Raw lengths require matching units and --units-evidence provenance")
    qc = dict(original_qc or {"inferred": branch_qc(inferred), "reference": branch_qc(reference)})
    if not all(value["valid"] for value in qc.values()):
        return dict(status="not_evaluated", reason="invalid_or_missing_lengths", qc=qc), []
    trees = [inferred.clone(depth=1), reference.clone(depth=1)]
    totals = [branch_qc(tree)["total"] for tree in trees]
    if length_mode == "total-length" and any(total <= 0 for total in totals):
        return dict(status="not_evaluated", reason="zero_total_length", qc=qc), []
    for tree, total in zip(trees, totals, strict=True):
        if length_mode == "total-length":
            for node in tree.preorder_node_iter():
                node.edge_length /= total
        tree.encode_bipartitions(suppress_unifurcations=False)
    paths = [PathDistances(tree) for tree in trees]
    rows = [dict(taxon_a=first, taxon_b=second,
                 inferred_distance=paths[0].distance(first, second),
                 reference_distance=paths[1].distance(first, second)) for first, second in pairs]
    result = dict(
        status="evaluated", length_mode=length_mode, qc=qc, aligned_totals=totals,
        inferred_units=inferred_units, reference_units=reference_units,
        units_evidence=units_evidence,
        patristic=distance_summary([row["inferred_distance"] for row in rows],
                                  [row["reference_distance"] for row in rows],
                                  errors=length_mode != "none"),
    )
    if length_mode != "none":
        score_trees = [tree.clone(depth=1) for tree in trees]
        for tree in score_trees:
            tree.suppress_unifurcations()
            tree.encode_bipartitions(suppress_unifurcations=False)
        result["branch_score_l2"] = treecompare.euclidean_distance(
            *score_trees, is_bipartitions_updated=True
        )
        result["weighted_rf_l1"] = treecompare.weighted_robinson_foulds_distance(
            *score_trees, is_bipartitions_updated=True
        )
    else:
        result.update(branch_score_l2=None, weighted_rf_l1=None,
                      error_reason="absolute_units_not_comparable")
    return result, rows