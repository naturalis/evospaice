"""Build an offline hierarchy explorer; Azure inputs and outputs stay in memory."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import logging
import platform
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit
from uuid import uuid4

import numpy as np
from Bio.Phylo.BaseTree import Tree

from evospaice.tree.centroid import RANKS, Dataset, build_tree, load_embeddings
from evospaice.tree.representations import METHODS, represent

LOGGER = logging.getLogger(__name__)
TEMPLATE = Path(__file__).with_name("explorer.html")
MARKER = "/* EXPLORER_DATA */ null"


def taxonomy_index(data: Dataset) -> tuple[list[dict], dict[tuple, int]]:
    """Index full paths once; store parent links and counts, not descendant lists."""
    taxa = [{"label": "Complete cohort", "rank": "cohort", "depth": 0,
             "parent": None, "children": [], "records": len(data.ids)}]
    paths: dict[tuple, int] = {(): 0}
    for identifier, row in zip(data.ids, data.taxonomy, strict=True):
        parent = 0
        path: tuple = ()
        for depth, label in enumerate([*map(str, row), str(identifier)], 1):
            path = (*path, label)
            if path not in paths:
                paths[path] = len(taxa)
                taxa[parent]["children"].append(len(taxa))
                taxa.append({
                    "label": label, "rank": RANKS[depth - 1] if depth <= 4 else "record",
                    "depth": depth, "parent": parent, "children": [], "records": 0,
                })
            parent = paths[path]
            taxa[parent]["records"] += 1
    return taxa, paths


def encode_hierarchy(tree: Tree, paths: dict[tuple, int]) -> dict:
    """Encode without modifying tree objects, retaining every edge and record."""
    nodes: list[dict] = []
    taxon_roots: dict[int, int] = {}
    stack = [(tree.root, (), None, True)]
    while stack:
        clade, path, parent, is_root = stack.pop()
        taxon = None
        if is_root:
            taxon = 0
        elif clade.is_terminal():
            path = (*path, str(clade.name))
            taxon = paths[path]
        elif len(path) < len(RANKS):
            prefix = RANKS[len(path)] + ":"
            if clade.name and clade.name.startswith(prefix):
                path = (*path, clade.name[len(prefix):])
                taxon = paths[path]
        index = len(nodes)
        nodes.append({"children": [], "length": float(clade.branch_length or 0),
                      "taxon": taxon, "label": clade.name or ""})
        if parent is not None:
            nodes[parent]["children"].append(index)
        if taxon is not None:
            if taxon in taxon_roots:
                raise ValueError("Tree contains a duplicate taxonomic path")
            taxon_roots[taxon] = index
        stack.extend((child, path, index, False) for child in reversed(clade.clades))
    if len(taxon_roots) != len(paths):
        raise ValueError("Tree does not cover every indexed taxon and record")
    return {"nodes": nodes, "root": 0, "taxonRoots": taxon_roots}


def representative_summaries(
    data: Dataset, tree: Tree, encoded: dict, paths: dict[tuple, int], method: str,
) -> dict:
    """Inspect fitted representatives without embedding vectors or covariance matrices.

    Non-Gaussian fits are deterministically replayed on the completed subtrees.
    GSC ignores each root's incoming edge, so later grafting does not alter its fit.
    Gaussian mean/trace use the exact raw-descendant sample moments directly.
    """
    groups: dict[tuple, list[int]] = {(): list(range(len(data.ids)))}
    for i, row in enumerate(data.taxonomy):
        for depth in range(1, len(RANKS) + 1):
            groups.setdefault(tuple(row[:depth]), []).append(i)
    clades = list(tree.find_clades(order="preorder"))
    summaries = {}
    for path, indices in groups.items():
        taxon = paths[path]
        vectors = data.embeddings[indices]
        raw_mean = vectors.mean(axis=0)
        if method == "wasserstein":
            summaries[taxon] = {
                "norm": float(np.linalg.norm(raw_mean)),
                "covarianceTrace": float(np.sum((vectors - raw_mean)**2) / (len(indices) - 1))
                if len(indices) > 1 else 0.0,
            }
            continue
        root = clades[encoded["taxonRoots"][taxon]]
        point = represent(vectors, list(map(str, data.ids[indices])), root, method, Counter())
        norm = float(np.linalg.norm(point))
        raw_norm = float(np.linalg.norm(raw_mean))
        summaries[taxon] = {
            "norm": norm,
            "cosineToRawMean": float(np.clip(
                1 - (point @ raw_mean) / (norm * raw_norm), 0, 2,
            )) if raw_norm > 0 else None,
        }
        if method == "medoid":
            record = int(np.flatnonzero(np.all(vectors == point, axis=1))[0])
            summaries[taxon]["medoidId"] = str(data.ids[indices[record]])
    return summaries


def generate_payload(
    data: Dataset, *, provenance: dict | None = None, max_children: int = 512,
) -> dict:
    """Fit all five full-cohort trees, without sampling, mutation, or disk output."""
    started = perf_counter()
    taxa, paths = taxonomy_index(data)
    trees, methods = {}, {}
    for method, description in METHODS.items():
        LOGGER.info("Starting %s: all %d records, %d dimensions",
                    method, len(data.ids), data.embeddings.shape[1])
        step = perf_counter()
        tree, diagnostics = build_tree(data, method=method, nj_backend="skbio",
                                       max_children=max_children)
        trees[method] = encode_hierarchy(tree, paths)
        trees[method]["representatives"] = representative_summaries(
            data, tree, trees[method], paths, method,
        )
        elapsed = perf_counter() - step
        methods[method] = {**description, "seconds": elapsed, "diagnostics": diagnostics}
        LOGGER.info("Finished %s in %.2fs (%d nodes)", method, elapsed,
                    len(trees[method]["nodes"]))
    return {
        "schemaVersion": 1, "records": len(data.ids), "dimensions": data.embeddings.shape[1],
        "taxa": taxa, "trees": trees, "methods": methods,
        "counts": {rank: sum(t["rank"] == rank for t in taxa) for rank in RANKS},
        "coverage": data.coverage, "provenance": provenance or {},
        "computation": {
            "scope": "All retained records at every rank; no additional subsampling",
            "backend": "skbio", "maxChildren": max_children,
            "seconds": perf_counter() - started,
            "createdUtc": datetime.now(UTC).isoformat(),
            "versions": {name: version(name) for name in ("numpy", "scipy", "scikit-bio")},
            "python": platform.python_version(), "machine": platform.machine(),
        },
    }


def render_html(payload: dict) -> str:
    """Embed inert JSON safely, including labels containing HTML/script delimiters."""
    serialized = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(MARKER) != 1:
        raise ValueError("Explorer template must contain exactly one data marker")
    return template.replace(MARKER, serialized)


def azure_prefix(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".blob.core.windows.net")
            or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment or len(parsed.path.strip("/").split("/")) < 2):
        raise ValueError(
            "Use an HTTPS Azure blob subset prefix without credentials or query string"
        )
    return value.rstrip("/") + "/"


class AzureMemoryStore:
    """Bearer-authenticated blob transfers; never persist or serialize access tokens."""

    def __init__(self, prefix: str, subscription: str):
        self.prefix = azure_prefix(prefix)
        self.subscription = subscription

    def request(self, name: str, data: bytes | None = None) -> bytes:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("Blob name must be a single safe filename")
        token = json.loads(subprocess.check_output([
            "az", "account", "get-access-token", "--resource", "https://storage.azure.com/",
            "--subscription", self.subscription, "-o", "json",
        ]))["accessToken"]
        headers = {"Authorization": f"Bearer {token}", "x-ms-version": "2023-11-03"}
        if data is not None:
            headers.update({"x-ms-blob-type": "BlockBlob", "If-None-Match": "*",
                            "Content-Type": "text/html; charset=utf-8"})
        request = urllib.request.Request(self.prefix + name, data=data, headers=headers,
                                         method="PUT" if data is not None else "GET")
        # Do not forward the bearer header to a redirect target.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, hdrs, newurl):
                return None

        with urllib.request.build_opener(NoRedirect).open(request, timeout=600) as response:
            if data is not None and response.status != 201:
                raise RuntimeError("Azure did not confirm blob creation")
            return response.read()

    def load(self, expected_records: int | None = None) -> tuple[Dataset, dict]:
        manifest_bytes = self.request("manifest.json")
        manifest = json.loads(manifest_bytes)
        contents = {}
        for name in ("embeddings.npz", "selected-records.tsv"):
            LOGGER.info("Reading %s into memory", name)
            contents[name] = self.request(name)
            artifact = manifest["artifacts"][name]
            if (hashlib.sha256(contents[name]).hexdigest() != artifact["sha256"]
                    or len(contents[name]) != artifact["bytes"]):
                raise ValueError(f"Manifest checksum/size mismatch: {name}")
        data = load_embeddings(io.BytesIO(contents["embeddings.npz"]), families=None)
        if data.coverage["source_records"] != len(data.ids):
            raise ValueError("Subset contains excluded records; refusing a silently reduced demo")
        if expected_records is not None and len(data.ids) != expected_records:
            raise ValueError(f"Expected {expected_records} records, received {len(data.ids)}")
        rows = list(csv.DictReader(io.StringIO(contents["selected-records.tsv"].decode()),
                                   delimiter="\t"))
        if len(rows) != len(data.ids):
            raise ValueError("Metadata record count differs from NPZ")
        for row, identifier, taxonomy in zip(rows, data.ids, data.taxonomy, strict=True):
            if row["id"] != identifier or any(row[rank] != taxonomy[i]
                                             for i, rank in enumerate(RANKS)):
                raise ValueError("Metadata IDs/taxonomy/order differs from NPZ")
        return data, {
            "subsetPrefix": self.prefix, "manifest": manifest,
            "manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "metadataVerified": "Every ID and full taxonomy matches the NPZ in source row order",
        }

    def publish(self, html: str) -> dict:
        name = f"merging-explorer-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:10]}.html"
        content = html.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        self.request(name, content)
        if hashlib.sha256(self.request(name)).hexdigest() != digest:
            raise ValueError("Uploaded HTML failed authenticated GET SHA-256 verification")
        return {"url": self.prefix + name, "bytes": len(content), "sha256": digest,
                "verified": "Authenticated GET matches uploaded SHA-256"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--azure-prefix", help="Private Azure subset containing NPZ, TSV, manifest")
    source.add_argument("--embeddings", type=Path, help="Existing NPZ; HTML streams to stdout")
    parser.add_argument("--subscription", help="Azure subscription for storage token acquisition")
    parser.add_argument(
        "--publish", action="store_true", help="Upload uniquely named HTML to prefix",
    )
    parser.add_argument("--expect-records", type=int)
    parser.add_argument("--max-children", type=int, default=512)
    args = parser.parse_args(argv)
    if args.azure_prefix and not args.subscription:
        parser.error("--azure-prefix requires --subscription")
    if args.publish and not args.azure_prefix:
        parser.error("--publish requires --azure-prefix")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    store = None
    if args.azure_prefix:
        store = AzureMemoryStore(args.azure_prefix, args.subscription)
        data, provenance = store.load(args.expect_records)
    else:
        source_bytes = args.embeddings.read_bytes()
        data = load_embeddings(io.BytesIO(source_bytes), families=None)
        provenance = {"input": str(args.embeddings),
                      "sha256": hashlib.sha256(source_bytes).hexdigest()}
        if args.expect_records is not None and len(data.ids) != args.expect_records:
            parser.error("Retained record count does not match --expect-records")
    payload = generate_payload(data, provenance=provenance, max_children=args.max_children)
    html = render_html(payload)
    if args.publish:
        result = store.publish(html)
        result["computation"] = payload["computation"]
        result["methods"] = {key: {"seconds": value["seconds"],
                                   "diagnostics": value["diagnostics"]}
                             for key, value in payload["methods"].items()}
        print(json.dumps(result, indent=2))
    else:
        sys.stdout.write(html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
