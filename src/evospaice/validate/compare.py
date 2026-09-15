"""Topology-only comparisons of phylogenetic trees using DendroPy."""

from __future__ import annotations

import gzip
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

import dendropy
from dendropy.calculate import treecompare


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


def prepare_trees(
    trees: Mapping[str, dendropy.Tree], *, mode: str, taxa_policy: str = "strict",
    mappings: Mapping[str, Mapping[str, str]] | None = None,
    selected: set[str] | None = None, max_tips: int = 5000,
) -> tuple[dict[str, dendropy.Tree], list[dict]]:
    """Align topology-only copies to one namespace and fixed benchmark set."""
    if not trees:
        raise ValueError("No trees supplied")
    if mode not in {"rooted", "unrooted"} or taxa_policy not in {"strict", "intersection"}:
        raise ValueError("Invalid rooting mode or taxa policy")
    if max_tips < 1:
        raise ValueError("max_tips must be positive")
    working, originals, sets = {}, {}, {}
    for name, tree in trees.items():
        labels = leaf_labels(tree)
        if len(labels) > max_tips:
            raise ValueError(f"{name}: tip limit exceeded; supply a subset or raise --max-tips")
        mapping = dict((mappings or {}).get(name, {}))
        if mapping.keys() - labels:
            raise ValueError(f"{name}: mapping contains labels absent from the tree")
        copy = tree.clone(depth=2)
        originals[name] = {}
        for node in copy.preorder_node_iter():
            node.edge_length = None
            if node.is_leaf():
                original = node.taxon.label
                canonical = mapping.get(original, original)
                originals[name][original] = canonical
                node.taxon.label = canonical
        sets[name] = leaf_labels(copy)
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
        tree.retain_taxa_with_labels(common)
        tree.migrate_taxon_namespace(namespace, unify_taxa_by_label=True)
        tree.encode_bipartitions()
    return working, coverage


def informative_splits(tree: dendropy.Tree) -> set[int]:
    """Return nontrivial rooted clades or canonical unrooted splits."""
    size = len(leaf_labels(tree))
    result = set()
    for node in tree.postorder_node_iter():
        mask = (node.bipartition.leafset_bitmask if tree.is_rooted
                else node.bipartition.split_bitmask)
        count = mask.bit_count()
        if 1 < count < size and (tree.is_rooted or size - count > 1):
            result.add(mask)
    return result


def split_id(mask: int, tree: dendropy.Tree) -> str:
    labels = [
        taxon.label for index, taxon in enumerate(tree.taxon_namespace) if mask & (1 << index)
    ]
    encoded = json.dumps(labels, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:20]


def topology_metrics(inferred: dendropy.Tree, reference: dendropy.Tree) -> tuple[dict, list[dict]]:
    """Compute RF, precision and recall for prepared trees, ignoring lengths."""
    first, second = informative_splits(inferred), informative_splits(reference)
    shared = len(first & second)
    denominator = len(first) + len(second)
    raw = treecompare.symmetric_difference(inferred, reference, is_bipartitions_updated=True)
    false_positive, false_negative = treecompare.false_positives_and_negatives(
        reference, inferred, is_bipartitions_updated=True
    )
    if raw != len(first ^ second) or raw != false_positive + false_negative:
        raise ValueError("DendroPy RF differs from informative split counts after normalization")
    rows = []
    for mask in sorted(first | second):
        origin = "both" if mask in first & second else "inferred" if mask in first else "reference"
        rows.append(dict(clade_id=split_id(mask, inferred), origin=origin,
                         size=mask.bit_count()))
    metrics = dict(
        kind="clade" if inferred.is_rooted else "split", rf=raw,
        rf_normalized=raw / denominator if denominator else None,
        rf_denominator=denominator, rf_normalization="observed_informative_splits",
        shared=shared, inferred_only=len(first - second), reference_only=len(second - first),
        inferred_count=len(first), reference_count=len(second),
        precision=shared / len(first) if first else None,
        recall=shared / len(second) if second else None,
        undefined_reasons={
            **({"precision": "no_inferred_relationships"} if not first else {}),
            **({"recall": "no_reference_relationships"} if not second else {}),
            **({"rf_normalized": "no_resolved_relationships"} if not denominator else {}),
        },
    )
    return metrics, rows