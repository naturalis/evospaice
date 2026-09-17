"""Simple taxonomy-constrained NJ baseline with sequence-weighted mean vectors."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import platform
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import numpy as np
from Bio import Phylo
from Bio.Phylo.BaseTree import Clade, Tree
from Bio.Phylo.TreeConstruction import DistanceMatrix, DistanceTreeConstructor
from scipy.spatial.distance import pdist, squareform
from scipy.stats import pearsonr, spearmanr

from evospaice.contracts.validators import UNKNOWN_SPECIES_VALUES
from evospaice.ingest.tsv2newick import NULL_VALUES
from evospaice.validate.compare import (
    leaf_labels,
    load_tree,
    prepare_trees,
    retain_labels,
    topology_metrics,
)

LOGGER = logging.getLogger(__name__)
RANKS = ("order", "family", "genus", "species")
BUTTERFLY_FAMILIES = (
    "Hedylidae", "Hesperiidae", "Lycaenidae", "Nymphalidae",
    "Papilionidae", "Pieridae", "Riodinidae",
)
MISSING_LABELS = NULL_VALUES | UNKNOWN_SPECIES_VALUES
NJ_BACKENDS = ("biopython", "skbio")


@dataclass(frozen=True)
class Dataset:
    ids: np.ndarray
    embeddings: np.ndarray
    taxonomy: np.ndarray
    coverage: dict[str, int]


@dataclass
class Subtree:
    root: Clade
    centroid: np.ndarray
    records: int


def load_embeddings(
    path: Path, families: tuple[str, ...] | None, selected_ids: set[str] | None = None
) -> Dataset:
    """Load the encoder NPZ without pickle, accounting for every excluded record."""
    with np.load(path, allow_pickle=False) as archive:
        required = {"ids", "embeddings", *RANKS}
        if missing := required - set(archive.files):
            raise ValueError(f"Missing NPZ arrays: {', '.join(sorted(missing))}")
        arrays = {key: archive[key] for key in ("ids", *RANKS)}
        count = len(arrays["ids"])
        for name, values in arrays.items():
            if values.shape != (count,) or values.dtype.kind not in "US":
                raise ValueError(f"{name} must be a one-dimensional string array of length {count}")
        ids = arrays["ids"].astype(str)
        taxonomy = np.column_stack([
            np.char.strip(arrays[rank].astype(str)) for rank in RANKS
        ])
        family_mask = (
            np.isin(taxonomy[:, 1], families) if families is not None else np.ones(count, bool)
        )
        id_mask = (
            np.isin(ids, sorted(selected_ids)) if selected_ids is not None else np.ones(count, bool)
        )
        complete = np.array([
            all(value.casefold() not in MISSING_LABELS for value in row) for row in taxonomy
        ])
        keep = family_mask & id_mask & complete
        if not keep.any():
            raise ValueError("No records remain after family, ID and taxonomy filtering")
        vectors = archive["embeddings"]
        if vectors.ndim != 2 or vectors.shape[0] != count or vectors.shape[1] == 0:
            raise ValueError("embeddings must have shape (number of IDs, positive dimension)")
        if vectors.dtype.kind not in "fi":
            raise ValueError("embeddings must contain real numeric values")
        vectors = np.asarray(vectors[keep], dtype=np.float64)
    if not np.isfinite(vectors).all() or np.any(np.linalg.norm(vectors, axis=1) == 0):
        raise ValueError("Selected embeddings contain non-finite or zero vectors")
    retained_ids = ids[keep]
    if any(not identifier.strip() for identifier in retained_ids):
        raise ValueError("Selected IDs must not be empty")
    if len(set(retained_ids)) != len(retained_ids):
        raise ValueError("Selected record IDs are not unique")
    return Dataset(
        retained_ids, vectors, taxonomy[keep],
        {
            "source_records": count,
            "outside_selected_families": int((~family_mask).sum()),
            "not_in_requested_ids": int((family_mask & ~id_mask).sum()),
            "incomplete_taxonomy": int((family_mask & id_mask & ~complete).sum()),
            "retained": int(keep.sum()),
        },
    )


def combine(
    name: str, children: list[Subtree], diagnostics: Counter, max_children: int,
    nj_backend: str = "biopython",
) -> Subtree:
    """Resolve child centroids with NJ, midpoint-root, and graft the full children."""
    if not children:
        raise ValueError(f"{name}: cannot combine an empty group")
    if len(children) > max_children:
        raise ValueError(
            f"{name} has {len(children)} children, exceeding --max-children={max_children}; "
            "select a smaller clade rather than silently dropping children"
        )
    count = sum(child.records for child in children)
    centroid = sum(
        (child.centroid * child.records for child in children),
        np.zeros_like(children[0].centroid),
    ) / count
    if not np.isfinite(centroid).all() or np.linalg.norm(centroid) == 0:
        raise ValueError(f"{name}: the arithmetic centroid is zero or non-finite")
    condensed = pdist(np.array([child.centroid for child in children]), metric="cosine")
    root = graft_nj(
        name, [child.root for child in children], np.clip(condensed, 0, 2),
        diagnostics, max_children, nj_backend,
    )
    return Subtree(root, centroid, count)


def _compiled_connector(
    distances: np.ndarray, tokens: list[str], diagnostics: Counter,
) -> Tree:
    from skbio import DistanceMatrix as NativeDistanceMatrix
    from skbio.tree import nj

    native = nj(NativeDistanceMatrix(distances, tokens), neg_as_zero=False, inplace=True)
    positive = False
    for node in native.traverse():
        if node.length is not None and node.length < 0:
            diagnostics["negative_edges_clamped"] += 1
            node.length = 0.0
        positive |= (node.length or 0) > 0
    if positive:
        native = native.root_at_midpoint(inplace=True, branch_attrs=[])
        diagnostics["midpoint_roots"] += 1
    else:
        diagnostics["zero_length_connectors"] += 1
    clades = {}
    for node in native.postorder():
        clades[node] = Clade(
            name=node.name, branch_length=node.length,
            clades=[clades[child] for child in node.children],
        )
    return Tree(root=clades[native], rooted=positive)


def graft_nj(
    name: str, roots: list[Clade], condensed: np.ndarray,
    diagnostics: Counter, max_children: int = 512, nj_backend: str = "biopython",
) -> Clade:
    """Share NJ resolution, root conventions, and grafting across representations."""
    if nj_backend not in NJ_BACKENDS:
        raise ValueError(f"Unknown NJ backend: {nj_backend}")
    if not roots or len(roots) > max_children:
        raise ValueError(f"{name}: require between 1 and {max_children} child trees")
    expected = len(roots) * (len(roots) - 1) // 2
    if condensed.shape != (expected,) or not np.isfinite(condensed).all():
        raise ValueError(f"{name}: invalid condensed distance matrix")
    if np.any(condensed < 0):
        raise ValueError(f"{name}: distances must be nonnegative")
    diagnostics["taxonomy_nodes"] += 1
    diagnostics["maximum_fanout"] = max(diagnostics["maximum_fanout"], len(roots))
    if len(roots) == 1:
        diagnostics["unary_nodes"] += 1
        roots[0].branch_length = 0.0
        return Clade(name=name, branch_length=0.0, clades=roots)
    if len(roots) >= 100:
        LOGGER.info("Resolving %s: %d child representatives (%s)", name, len(roots), nj_backend)
    started = perf_counter()
    distances = squareform(condensed)
    tokens = [f"child_{i}" for i in range(len(roots))]
    if nj_backend == "skbio" and len(roots) >= 3:
        connector = _compiled_connector(distances, tokens, diagnostics)
        diagnostics["skbio_nj_merges"] += 1
    else:
        connector = DistanceTreeConstructor().nj(DistanceMatrix(
            tokens, [distances[i, :i + 1].tolist() for i in range(len(roots))]
        ))
        diagnostics["biopython_nj_merges"] += 1
        for clade in connector.find_clades():
            if clade.branch_length is not None and clade.branch_length < 0:
                diagnostics["negative_edges_clamped"] += 1
                clade.branch_length = 0.0
        if any((clade.branch_length or 0) > 0 for clade in connector.find_clades()):
            connector.root_at_midpoint()
            diagnostics["midpoint_roots"] += 1
        else:
            diagnostics["zero_length_connectors"] += 1
    diagnostics["nj_merges"] += 1
    diagnostics["local_distance_pairs"] += len(condensed)
    # Capture connector slots before grafting so traversal never enters child trees.
    slots = [
        (parent, index, child.name, child.branch_length)
        for parent in connector.find_clades()
        for index, child in enumerate(parent.clades) if child.is_terminal()
    ]
    lookup = dict(zip(tokens, roots, strict=True))
    for parent, index, token, length in slots:
        child = lookup[token]
        child.branch_length = length or 0.0
        parent.clades[index] = child
    connector.root.name = name
    connector.root.branch_length = 0.0
    if len(roots) >= 100:
        LOGGER.info("Resolved %s in %.2f seconds", name, perf_counter() - started)
    return connector.root


def build_tree(
    data: Dataset, max_children: int = 512, nj_backend: str = "biopython",
) -> tuple[Tree, dict]:
    if nj_backend not in NJ_BACKENDS:
        raise ValueError(f"Unknown NJ backend: {nj_backend}")
    if max_children < 2:
        raise ValueError("max_children must be at least two")
    diagnostics: Counter = Counter()

    def visit(indices: list[int], depth: int, name: str) -> Subtree:
        if depth == len(RANKS):
            children = [
                Subtree(Clade(name=str(data.ids[i]), branch_length=0.0), data.embeddings[i], 1)
                for i in indices
            ]
        else:
            groups: dict[str, list[int]] = {}
            for i in indices:
                groups.setdefault(str(data.taxonomy[i, depth]), []).append(i)
            children = [
                visit(group, depth + 1, f"{RANKS[depth]}:{label}")
                for label, group in sorted(groups.items())
            ]
        return combine(name, children, diagnostics, max_children, nj_backend)

    result = visit(list(range(len(data.ids))), 0, "butterfly_centroid_baseline")
    if diagnostics["negative_edges_clamped"]:
        LOGGER.warning(
            "Clamped %d negative NJ edges to zero", diagnostics["negative_edges_clamped"]
        )
    return Tree(root=result.root, rooted=True), dict(diagnostics)


def sampled_pairs(count: int, limit: int, seed: int) -> list[tuple[int, int]]:
    if count < 2 or limit < 1:
        raise ValueError(
            "Distance evaluation requires at least two leaves and a positive pair limit"
        )
    total = count * (count - 1) // 2
    if total <= limit:
        return [(i, j) for i in range(count) for j in range(i + 1, count)]
    rng = np.random.default_rng(seed)
    selected: set[tuple[int, int]] = set()
    while len(selected) < limit:
        a, b = map(int, rng.choice(count, size=2, replace=False))
        selected.add((min(a, b), max(a, b)))
    return sorted(selected)


def tree_pair_distances(tree, ids: np.ndarray, pairs: list[tuple[int, int]]) -> np.ndarray:
    """Compare sampled paths in O(sum of leaf depths), not an all-pairs tree matrix."""
    node_distance = {}
    routes = {}
    stack = [(tree.seed_node, (), 0.0)]
    while stack:
        node, ancestors, parent_distance = stack.pop()
        distance = parent_distance + (node.edge_length or 0.0)
        if not np.isfinite(distance):
            raise ValueError("Tree contains non-finite path lengths")
        node_distance[node] = distance
        route = (*ancestors, node)
        if node.is_leaf():
            routes[node.taxon.label] = route
        else:
            stack.extend((child, route, distance) for child in node.child_node_iter())
    result = []
    for a, b in pairs:
        first, second = routes[str(ids[a])], routes[str(ids[b])]
        ancestor = first[0]
        for left, right in zip(first, second, strict=False):
            if left is not right:
                break
            ancestor = left
        result.append(node_distance[first[-1]] + node_distance[second[-1]]
                      - 2 * node_distance[ancestor])
    return np.array(result)


def distance_metrics(target: np.ndarray, predicted: np.ndarray) -> dict:
    if float(target @ target) == 0:
        raise ValueError("Normalized stress is undefined for all-zero target distances")
    error = predicted - target
    variable = len(target) > 1 and np.ptp(target) > 0 and np.ptp(predicted) > 0
    return {
        "pairs": len(target),
        "normalized_stress": float(np.linalg.norm(error) / np.linalg.norm(target)),
        "mean_signed_error": float(error.mean()),
        "p90_absolute_error": float(np.quantile(np.abs(error), 0.9)),
        "pearson": float(pearsonr(target, predicted).statistic) if variable else None,
        "spearman": float(spearmanr(target, predicted).statistic) if variable else None,
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(
    embeddings: Path, output: Path, match_ids: Path | None = None,
    reference: Path | None = None, families: tuple[str, ...] | None = BUTTERFLY_FAMILIES,
    max_children: int = 512, pair_limit: int = 5000, seed: int = 42,
    source_uri: str | None = None, nj_backend: str = "biopython",
) -> dict:
    started = perf_counter()
    if output.exists():
        raise FileExistsError(f"{output} already exists; choose a new output directory")
    selected = set(match_ids.read_text().splitlines()) if match_ids is not None else None
    data = load_embeddings(embeddings, families, selected)
    LOGGER.info("Selected %d real records: %s", len(data.ids), data.coverage)
    tree, diagnostics = build_tree(data, max_children, nj_backend)
    LOGGER.info("Tree assembled in %.2f seconds; writing and evaluating", perf_counter() - started)
    if families is None:
        tree.root.name = "taxonomy_centroid_baseline"
    output.mkdir(parents=True)
    tree_path = output / "centroid.nwk"
    Phylo.write(tree, tree_path, "newick", format_branch_length="%1.12g")
    inferred = load_tree(tree_path)
    if leaf_labels(inferred) != set(data.ids):
        raise ValueError("Serialized tree leaves differ from the selected record IDs")
    pairs = sampled_pairs(len(data.ids), pair_limit, seed)
    unit = data.embeddings / np.linalg.norm(data.embeddings, axis=1, keepdims=True)
    target = np.array([np.clip(1 - unit[a] @ unit[b], 0, 2) for a, b in pairs])
    predicted = tree_pair_distances(inferred, data.ids, pairs)
    evaluation = distance_metrics(target, predicted)
    by_rank = {}
    for depth, rank in enumerate((*RANKS, "within_species")):
        indices = [
            i for i, (a, b) in enumerate(pairs)
            if next((j for j in range(4) if data.taxonomy[a, j] != data.taxonomy[b, j]), 4)
            == depth
        ]
        by_rank[rank] = (
            distance_metrics(target[indices], predicted[indices]) if indices else None
        )
    report = {
        "input": {"path": str(embeddings), "sha256": sha256(embeddings), "uri": source_uri},
        "selection": {
            "families": list(families) if families is not None else None,
            "complete_taxonomy_required": True,
            "match_ids": str(match_ids) if match_ids is not None else None,
            "max_children": max_children,
        },
        "algorithm": {
            "representative": "arithmetic mean of all raw stored descendant vectors",
            "propagation": "child centroids weighted by their descendant record counts",
            "distance": "cosine", "local_resolution": "Neighbor-Joining",
            "nj_backend": nj_backend,
            "nj_backend_version": version("scikit-bio" if nj_backend == "skbio" else "biopython"),
            "rooting": "midpoint convention, not a biological root",
            "grafting": "replace NJ representative tips with complete child subtrees",
            "negative_edges": "clamped to zero and counted",
            "attachment_offset_correction": False,
        },
        "coverage": data.coverage, "dimensions": data.embeddings.shape[1],
        "families": dict(Counter(map(str, data.taxonomy[:, 1]))),
        "taxon_counts": {
            rank: len({tuple(row[:depth + 1]) for row in data.taxonomy})
            for depth, rank in enumerate(RANKS)
        },
        "diagnostics": diagnostics, "sample_seed": seed,
        "evaluation": {"embedding_distance": evaluation, "by_first_differing_rank": by_rank},
        "evaluation_scope": "descriptive sampled-pair fit, not a held-out generalization test",
    }
    if reference is not None:
        LOGGER.info("Loading the independent reference tree")
        reference_tree = load_tree(reference)
        reference_labels = leaf_labels(reference_tree)
        if missing := set(data.ids) - reference_labels:
            raise ValueError(f"{len(missing)} selected IDs are absent from the reference tree")
        retain_labels(reference_tree, set(data.ids))
        reference_distances = tree_pair_distances(reference_tree, data.ids, pairs)
        prepared, _ = prepare_trees(
            {"inferred": inferred, "reference": reference_tree}, mode="unrooted"
        )
        topology, _ = topology_metrics(prepared["inferred"], prepared["reference"])
        report["reference"] = {
            "path": str(reference), "sha256": sha256(reference),
            "original_tips": len(reference_labels), "matched_tips": len(data.ids),
            "unrooted_topology": topology,
            "path_comparison": distance_metrics(reference_distances, predicted),
            "length_warning": "reference and embedding branch lengths use different scales",
        }
        reference_tree.write(path=str(output / "reference-matched.nwk"), schema="newick")
    with (output / "selected-records.tsv").open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(("id", *RANKS))
        writer.writerows((identifier, *row) for identifier, row in zip(
            data.ids, data.taxonomy, strict=True
        ))
    with (output / "evaluated-pairs.tsv").open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(("id_a", "id_b", "embedding_distance", "tree_distance"))
        writer.writerows((data.ids[a], data.ids[b], float(target[i]), float(predicted[i]))
                         for i, (a, b) in enumerate(pairs))
    report["runtime"] = {
        "seconds": perf_counter() - started, "architecture": platform.machine(),
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--match-ids", type=Path)
    parser.add_argument("--reference-tree", type=Path)
    family_selection = parser.add_mutually_exclusive_group()
    family_selection.add_argument(
        "--families", nargs="+", default=list(BUTTERFLY_FAMILIES),
        help="Family labels to include (default: the seven butterfly families)",
    )
    family_selection.add_argument(
        "--all-families", action="store_true",
        help="Include every family in the input; complete taxonomy is still required",
    )
    parser.add_argument("--max-children", type=int, default=512)
    parser.add_argument(
        "--nj-backend", choices=NJ_BACKENDS, default="biopython",
        help=(
            "skbio uses compiled NJ and efficient midpoint rooting; "
            "biopython preserves the baseline"
        ),
    )
    parser.add_argument("--pairs", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--source-uri")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        report = run(
            args.embeddings, args.output_dir, args.match_ids, args.reference_tree,
            None if args.all_families else tuple(args.families),
            args.max_children, args.pairs, args.seed, args.source_uri,
            args.nj_backend,
        )
    except (OSError, ValueError, ImportError) as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    print(json.dumps({
        "records": report["coverage"]["retained"], "taxa": report["taxon_counts"],
        "embedding_fit": report["evaluation"]["embedding_distance"],
        "reference": report.get("reference"), "output": str(args.output_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
