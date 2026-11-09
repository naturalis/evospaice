"""Compare the survey's five representations on one fixed real genus cohort."""

from __future__ import annotations

import argparse
import csv
import json
import logging
from collections.abc import Sequence
from itertools import combinations
from pathlib import Path

import numpy as np
from Bio import Phylo
from Bio.Phylo.BaseTree import Tree
from scipy.spatial.distance import pdist

from evospaice.tree.centroid import (
    BUTTERFLY_FAMILIES,
    Dataset,
    build_tree,
    distance_metrics,
    load_embeddings,
    sha256,
    tree_pair_distances,
)
from evospaice.tree.representations import (
    METHODS as METHODS,
)
from evospaice.tree.representations import (
    gaussian as gaussian,
)
from evospaice.tree.representations import (
    gaussian_w2 as gaussian_w2,
)
from evospaice.tree.representations import (
    gsc_weights as gsc_weights,
)
from evospaice.tree.representations import (
    spherical_mean as spherical_mean,
)
from evospaice.validate.compare import (
    leaf_labels,
    load_tree,
    prepare_trees,
    retain_labels,
    topology_metrics,
)


def build_genus(data: Dataset, method: str) -> tuple[Tree, dict]:
    """Compatibility wrapper around the shared full-depth builder."""
    if method not in METHODS:
        raise ValueError(f"Unknown representation: {method}")
    genera = {tuple(row[:3]) for row in data.taxonomy}
    if len(genera) != 1:
        raise ValueError("Comparison requires exactly one genus")
    return build_tree(data, method=method, start_rank=3,
                      root_name=f"genus:{next(iter(genera))[2]}")


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
        common["raw_magnitude_comparable"] = name not in {"wasserstein", "reference"}
        if not common["raw_magnitude_comparable"]:
            for key in ("normalized_stress", "mean_signed_error", "p90_absolute_error"):
                common[key] = None
        denominator = float(paths[name] @ paths[name])
        scale = max(0.0, float(cosine @ paths[name] / denominator)) if denominator > 0 else None
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
            ] if scale is not None else None,
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
            "cross_unit_errors": "Raw W2/reference magnitude errors against cosine are null; "
                                 "only correlations and explicitly fitted scales are comparable",
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
        correlation = entry["cosine_comparison"]["spearman"]
        formatted = f"{correlation:.4f}" if correlation is not None else "undefined"
        print(
            f"{name}: RF vs centroid={entry['rf_to_centroid']['rf']}, "
            f"RF vs reference={entry['rf_to_reference']['rf']}, "
            f"cosine Spearman={formatted}"
        )
    print(f"Comparison: {args.output_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
