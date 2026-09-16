"""Static algorithm-review metrics on an exact shared-ID whole-tree cohort."""

from __future__ import annotations

import argparse
import csv
import gc
import json
import logging
import sys
from importlib.metadata import version
from pathlib import Path
from time import perf_counter

import numpy as np
from dendropy.utility.error import DataParseError

from evospaice.tree.centroid import load_embeddings, sampled_pairs, sha256

from .compare import leaf_labels, load_tree, prepare_trees, retain_labels, topology_metrics
from .tree_metrics import (
    TreeIndex,
    errors,
    fitted_errors,
    kc_topology,
    neighbor_preservation,
    taxon_purity,
)

LOGGER = logging.getLogger(__name__)


def _kc(prepared: dict, labels: list[str], pairs: np.ndarray) -> tuple[dict, dict]:
    depths = {}
    outgroup = labels[0]
    for name, tree in prepared.items():
        tip = tree.find_node_with_taxon_label(outgroup)
        tree.reroot_at_edge(tip.edge, length1=0, length2=0, suppress_unifurcations=True)
        index = TreeIndex(tree, lengths=False)
        leaves = index.leaves(labels)
        depths[name] = index.depth[index.lca(leaves[pairs[:, 0]], leaves[pairs[:, 1]])]
    result = kc_topology(depths["centroid"], depths["reference"], len(labels))
    result["rooting"] = {
        "policy": "both trees rooted on the same lexicographically first shared tip edge",
        "outgroup_id": outgroup, "biological_root": False, "unary_nodes": "suppressed",
    }
    return result, depths


def _table(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, separators=(",", ":")) if isinstance(value, (list, dict))
                else value for key, value in row.items()
            })


def run(
    inferred: Path, reference: Path, embeddings: Path, output: Path,
    *, pair_limit: int = 50000, anchors: int = 128, k: int = 10, seed: int = 42,
) -> dict:
    started = perf_counter()
    if output.exists():
        raise FileExistsError(f"{output} already exists; choose a new output directory")
    if pair_limit < 1 or anchors < 1 or k < 1 or seed < 0:
        raise ValueError("Pair/anchor counts and k must be positive; seed must be nonnegative")
    paths = {"centroid": inferred, "reference": reference}
    LOGGER.info("Loading both whole trees")
    trees = {name: load_tree(path) for name, path in paths.items()}
    originals = {name: leaf_labels(tree) for name, tree in trees.items()}
    labels = sorted(originals["centroid"] & originals["reference"])
    if len(labels) < 4:
        raise ValueError("Whole-tree comparison requires at least four shared record IDs")
    if k >= len(labels):
        raise ValueError("k must be smaller than the shared cohort")
    LOGGER.info("Matching %d record IDs; loading their embeddings and taxonomy", len(labels))
    data = load_embeddings(embeddings, None, set(labels))
    if set(data.ids) != set(labels):
        raise ValueError("Every shared record must have an embedding and complete taxonomy")
    source_index = {str(label): i for i, label in enumerate(data.ids)}
    order = np.array([source_index[label] for label in labels])
    vectors, taxonomy = data.embeddings[order], data.taxonomy[order]
    unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    del data, vectors
    pairs = np.array(sampled_pairs(len(labels), pair_limit, seed), dtype=np.int64)
    LOGGER.info("Computing exact unrooted RF across all shared tips")
    prepared, coverage = prepare_trees(trees, mode="unrooted", taxa_policy="intersection")
    topology, _ = topology_metrics(
        prepared["centroid"], prepared["reference"], include_clades=False,
    )
    LOGGER.info("Computing sampled topology-only Kendall-Colijn distance")
    kc, kc_depths = _kc(prepared, labels, pairs)
    del prepared
    gc.collect()
    for tree in trees.values():
        retain_labels(tree, set(labels))
    indices = {name: TreeIndex(tree) for name, tree in trees.items()}
    sampled_paths = {}
    for name, index in indices.items():
        leaves = index.leaves(labels)
        sampled_paths[name] = index.paths(leaves[pairs[:, 0]], leaves[pairs[:, 1]])
    cosine = np.clip(1 - np.einsum(
        "ij,ij->i", unit[pairs[:, 0]], unit[pairs[:, 1]],
    ), 0, 2)
    LOGGER.info("Computing taxonomy purity and sampled distance fidelity")
    purity, taxon_rows = taxon_purity(indices, labels, taxonomy)
    embedding_fit = {
        name: {
            "raw": errors(cosine, distances),
            "scale_aligned": fitted_errors(cosine, distances),
            "raw_magnitude_comparable": name == "centroid",
        } for name, distances in sampled_paths.items()
    }
    path_fit = {
        "raw": errors(sampled_paths["reference"], sampled_paths["centroid"]),
        "scale_aligned": fitted_errors(sampled_paths["reference"], sampled_paths["centroid"]),
        "raw_magnitude_comparable": False,
    }
    LOGGER.info(
        "Computing exact %d-neighbor sets for %d sampled anchors", k, min(anchors, len(labels)),
    )
    neighbors, neighbor_rows = neighbor_preservation(
        indices, labels, unit, k=k, anchors=anchors, seed=seed + 1,
    )
    report = {
        "schema_version": 1,
        "scope": "Whole-tree comparison on the exact shared-ID cohort, not a genus subset",
        "metric_sources": [
            "docs/dna-tree-algorithmic-literature-survey.html, section 4",
            "Kendall & Colijn (2016), https://doi.org/10.1093/molbev/msw124",
        ],
        "inputs": {
            name: {"path": str(path), "sha256": sha256(path)}
            for name, path in {**paths, "embeddings": embeddings}.items()
        },
        "coverage": {
            "shared_tips": len(labels),
            **{
                name: {
                    "original_tips": len(original), "retained_tips": len(labels),
                    "excluded_tips": len(original) - len(labels),
                    "retained_fraction": len(labels) / len(original),
                } for name, original in originals.items()
            },
            "policy": "exact case-sensitive record-ID intersection; no label or BIN remapping",
        },
        "sampling": {
            "seed": seed, "sampled_pairs": len(pairs),
            "possible_pairs": len(labels) * (len(labels) - 1) // 2,
            "all_pairs_evaluated": len(pairs) == len(labels) * (len(labels) - 1) // 2,
            "policy": "uniform unordered pairs without replacement; descriptive, not held out",
        },
        "topology": {"rf": topology, "kendall_colijn": kc},
        "taxonomic_purity": {
            "by_rank": purity,
            "definition": "taxon record count / descendant tip count of that taxon's MRCA",
            "rooting": "supplied roots after shared-ID pruning; root-dependent",
            "warning": "Centroid taxonomy is imposed during construction; its purity is a "
                       "constraint check, not independent biological accuracy. Singleton taxa "
                       "have trivial purity one and are reported separately.",
        },
        "embedding_fidelity": embedding_fit,
        "reference_path_comparison": path_fit,
        "neighbors": neighbors,
        "not_computed": {
            "merge_height_cpcc": "NJ trees are non-ultrametric; report patristic Pearson instead",
            "kc_with_branch_lengths": "lambda > 0 mixes incompatible branch-length units",
            "bootstrap_support": "requires an explicit perturbation model and replicate trees; "
                                 "embedding noise is not a classical sequence-site bootstrap",
            "subsampling_invariance": "requires subsampled rebuilds and defined assignment rules",
        },
        "interpretation": [
            "The reference is a Bactria sequence-derived estimate and may share taxonomic "
            "constraints. These comparisons do not establish independent biological accuracy.",
            "RF uses every informative unrooted split on all matched tips, including splits "
            "whose lengths were clamped to zero. Branch lengths and supplied roots are ignored.",
            "KC uses root-to-MRCA edge counts, not leaf-to-MRCA distances. Its rooting and "
            "bounded normalization are stated explicitly; sampled estimates are not exact scores.",
            "Patristic Pearson compares leaf-to-leaf path distances, not dendrogram merge "
            "heights. Correlation above the review's suggested 0.85 is not proof of "
            "low distortion.",
            "Review stress is sum squared errors / sum squared targets, with no square root. "
            "The earlier centroid report's normalized_stress is its square root.",
            "Reference sequence lengths and centroid cosine-derived lengths have different "
            "units. Raw reference magnitude errors are diagnostic only, not a calibrated score.",
            "Scalar alignment is fitted on the same sampled pairs, not held-out calibration.",
            "MAPE excludes exactly zero targets and reports their count; near-zero targets "
            "can still dominate the percentage error.",
        ],
        "versions": {name: version(name) for name in ("numpy", "scipy", "dendropy")},
        "runtime_seconds": perf_counter() - started,
    }
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    template = Path(__file__).parents[1] / "viz" / "validation_report.html"
    html = template.read_text().replace(
        "/* VALIDATION_DATA */ null",
        json.dumps(report, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c"),
    )
    output.mkdir(parents=True)
    for name, tree in trees.items():
        tree.write(path=str(output / f"{name}-matched.nwk"), schema="newick")
    _table(output / "taxa.tsv", coverage)
    _table(output / "taxon-purity.tsv", taxon_rows)
    _table(output / "neighbors.tsv", neighbor_rows)
    _table(output / "evaluated-pairs.tsv", [
        {
            "id_a": labels[a], "id_b": labels[b], "embedding_cosine": float(cosine[i]),
            **{f"{name}_path": float(distances[i]) for name, distances in sampled_paths.items()},
            **{f"{name}_kc_mrca_depth": int(depth[i]) for name, depth in kc_depths.items()},
        } for i, (a, b) in enumerate(pairs)
    ])
    (output / "report.json").write_text(serialized)
    (output / "index.html").write_text(html)
    LOGGER.info("Saved whole-tree metrics to %s", output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inferred", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--embeddings", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=50000)
    parser.add_argument("--anchors", type=int, default=128)
    parser.add_argument("--neighbors", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        report = run(
            args.inferred, args.reference, args.embeddings, args.output_dir,
            pair_limit=args.pairs, anchors=args.anchors, k=args.neighbors, seed=args.seed,
        )
    except (OSError, ValueError, DataParseError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "shared_tips": report["coverage"]["shared_tips"],
        "rf": report["topology"]["rf"],
        "kc_normalized": report["topology"]["kendall_colijn"]["normalized"],
        "centroid_embedding_fidelity": report["embedding_fidelity"]["centroid"]["raw"],
        "neighbors": report["neighbors"]["mean_precision_at_k"],
        "output": str(args.output_dir),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
