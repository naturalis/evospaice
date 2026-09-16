"""RF topology comparisons and supplied-root tip-to-root correlation."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import dendropy
from dendropy.calculate import treecompare


def root_to_node_lengths(tree: dendropy.Tree, *, name: str) -> tuple[list[dict], dict[str, float]]:
    """Measure every original node from the supplied root without mutating it."""
    try:
        leaf_labels(tree)
    except ValueError as error:
        raise ValueError(f"{name}: {error}") from error
    rows, tips = [], {}
    pending: list[tuple[dendropy.Node, int | None, float]] = [(tree.seed_node, None, 0.0)]
    while pending:
        node, parent_id, parent_sum = pending.pop()
        node_id = len(rows)
        label = node.taxon.label if node.taxon else node.label
        total = 0.0
        if parent_id is not None:
            length = node.edge_length
            location = f"{name}: node {node_id} (label={label!r})"
            if length is None or not math.isfinite(length) or length < 0:
                raise ValueError(
                    f"{location}: edge length must be finite and nonnegative; got {length!r}"
                )
            total = parent_sum + length
            if not math.isfinite(total):
                raise ValueError(f"{location}: non-finite cumulative root-to-node length")
        rows.append(dict(tree=name, node_id=node_id, parent_id=parent_id,
                         original_label=label, node_kind="tip" if node.is_leaf() else "internal",
                         root_to_node_sum=total))
        if node.is_leaf():
            tips[label] = total
        pending.extend((child, node_id, total) for child in reversed(node.child_nodes()))
    return rows, tips


def tip_to_root_correlation(
    reference: Sequence[tuple[str, float]], inferred: Sequence[tuple[str, float]], *,
    retained_taxa: set[str],
) -> tuple[dict, list[dict]]:
    """Align unique retained identities and compare tip depths using SciPy."""
    from scipy.stats import rankdata, spearmanr

    aligned = {}
    for name, values in (("reference", reference), ("inferred", inferred)):
        labels = [label for label, _ in values]
        if len(labels) != len(set(labels)):
            raise ValueError(f"{name}: duplicate canonical tip IDs in length comparison")
        if set(labels) != retained_taxa:
            raise ValueError(
                f"{name}: canonical tip IDs differ from retained taxa; "
                f"missing={sorted(retained_taxa - set(labels))}, "
                f"unexpected={sorted(set(labels) - retained_taxa)}"
            )
        lookup = dict(values)
        for label, value in values:
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name}: tip {label!r} requires a finite nonnegative length")
        aligned[name] = [lookup[label] for label in sorted(retained_taxa)]
    if len(retained_taxa) < 3:
        raise ValueError("tip-to-root-correlation requires at least three matched tips")
    ranks = {name: rankdata(values, method="average") for name, values in aligned.items()}
    constant = [name for name, values in aligned.items() if min(values) == max(values)]
    rho = None
    if not constant:
        rho = float(spearmanr(aligned["reference"], aligned["inferred"]).statistic)
    result = dict(
        rho=rho,
        compared_tip_count=len(retained_taxa), status="undefined" if constant else "ok",
    )
    if constant:
        result["undefined_reason"] = "Constant tip-to-root lengths in " + " and ".join(constant)
    rows = [dict(taxon=label, reference_sum=aligned["reference"][index],
                 inferred_sum=aligned["inferred"][index],
                 reference_rank=float(ranks["reference"][index]),
                 inferred_rank=float(ranks["inferred"][index]))
            for index, label in enumerate(sorted(retained_taxa))]
    return result, rows


def leaf_labels(tree: dendropy.Tree) -> set[str]:
    """Require unique, nonempty leaf labels without changing case or punctuation."""
    labels: set[str] = set()
    for node in tree.leaf_node_iter():
        label = node.taxon.label if node.taxon else None
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Every tree leaf must have a nonempty taxon label")
        if label in labels:
            raise ValueError("Tree leaf labels must be unique")
        labels.add(label)
    return labels


def load_tree(
    path: Path, *, max_bytes: int = 32 * 1024**2
) -> dendropy.Tree:
    """Read a single Newick with bounded decompressed size."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        content = handle.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError("Tree input size limit exceeded; provide a benchmark clade subset")
    trees = dendropy.TreeList.get(
        data=content.decode("utf-8"), schema="newick", preserve_underscores=True,
        taxon_namespace=dendropy.TaxonNamespace(is_case_sensitive=True),
        case_sensitive_taxon_labels=True, extract_comment_metadata=True,
    )
    if len(trees) != 1:
        raise ValueError("Each comparison input must contain exactly one tree")
    leaf_labels(trees[0])
    return trees[0]


def prepare_trees(
    trees: Mapping[str, dendropy.Tree], *, mode: str, taxa_policy: str = "strict",
    mappings: Mapping[str, Mapping[str, str]] | None = None,
    selected: set[str] | None = None, require_rf: bool = True,
) -> tuple[dict[str, dendropy.Tree], list[dict]]:
    """Align topology-only copies to one namespace and fixed benchmark set."""
    if not trees:
        raise ValueError("No trees supplied")
    if mode not in {"rooted", "unrooted"} or taxa_policy not in {"strict", "intersection"}:
        raise ValueError("Invalid rooting mode or taxa policy")
    working, originals, sets = {}, {}, {}
    for name, tree in trees.items():
        labels = leaf_labels(tree)
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
    minimum = 4 if require_rf and mode == "unrooted" else 3
    if len(common) < minimum:
        comparison = mode if require_rf else "tip-to-root-correlation"
        raise ValueError(f"{comparison} comparison requires at least {minimum} shared tips")
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
    """Compute raw and normalized RF for prepared trees, ignoring lengths."""
    first, second = informative_splits(inferred), informative_splits(reference)
    for name, relationships in (("inferred", first), ("reference", second)):
        if not relationships:
            kind = "clade" if inferred.is_rooted else "split"
            raise ValueError(
                f"{name} tree must have at least one informative {kind} after taxa alignment"
            )
    shared = len(first & second)
    denominator = len(first) + len(second)
    raw = treecompare.symmetric_difference(inferred, reference, is_bipartitions_updated=True)
    if raw != len(first ^ second):
        raise ValueError("DendroPy RF differs from informative split counts after normalization")
    rows = []
    for mask in sorted(first | second):
        origin = "both" if mask in first & second else "inferred" if mask in first else "reference"
        rows.append(dict(clade_id=split_id(mask, inferred), origin=origin,
                         size=mask.bit_count()))
    metrics = dict(
        kind="clade" if inferred.is_rooted else "split", rf=raw,
        rf_normalized=raw / denominator,
        rf_denominator=denominator, rf_normalization="observed_informative_splits",
        shared=shared, inferred_only=len(first - second), reference_only=len(second - first),
        inferred_count=len(first), reference_count=len(second),
    )
    return metrics, rows