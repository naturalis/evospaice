"""Command-line entry point for evospaice."""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Optional, Sequence

from evospaice.tree import InputPaths, TreeBuildConfig, build_tree

try:
    __version__ = version("evospaice")
except PackageNotFoundError:  # running from a source checkout that isn't installed
    __version__ = "0.0.0+dev"

# Track -> one-line description, mirrored from the src/evospaice/<track>/README.md files.
# Adding a track here gives it a subcommand automatically.
TRACKS: dict[str, str] = {
    "ingest": "Trim to primer window, dereplicate within taxon, embed records.",
    "tree": "Resolve the backbone bottom-up (NJ) and assign branch lengths.",
    "validate": "Check embedding distances are a faithful metric, not just a good ID.",
    "viz": "Render the scaled tree.",
    "diversity": "Alpha/beta phylogenetic diversity and curation outliers.",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser and its track subcommands."""
    parser = argparse.ArgumentParser(
        prog="evospaice",
        description="Build a scaled reference tree from barcode embeddings.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="track", metavar="<track>")
    for name, help_text in TRACKS.items():
        track_parser = subparsers.add_parser(name, help=help_text)
        if name == "tree":
            _configure_tree_parser(track_parser)
    return parser


def _configure_tree_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--records", type=Path)
    parser.add_argument("--embeddings", type=Path)
    parser.add_argument("--embedding-index", type=Path)
    parser.add_argument("--trust-policy", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--storage-account-url")
    parser.add_argument("--container")
    parser.add_argument("--input-prefix")
    parser.add_argument("--output-prefix")
    parser.add_argument("--cloud-embeddings-name", default="embeddings.npy")
    parser.add_argument("--max-nj-children", type=int, default=256)
    parser.add_argument("--centroid-drift-limit", type=float, default=0.35)
    parser.add_argument("--fallback-branch-length", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)


def _run_tree(args: argparse.Namespace) -> int:
    config = TreeBuildConfig(
        max_nj_children=args.max_nj_children,
        centroid_drift_limit=args.centroid_drift_limit,
        fallback_branch_length=args.fallback_branch_length,
        random_seed=args.seed,
    )
    cloud_values = (
        args.storage_account_url,
        args.container,
        args.input_prefix,
        args.output_prefix,
    )
    if any(cloud_values):
        if not all(cloud_values):
            raise ValueError(
                "cloud mode requires --storage-account-url, --container, "
                "--input-prefix, and --output-prefix"
            )
        from evospaice.tree.cloud import BlobObjectStore, CloudRunConfig, run_cloud_tree

        result = run_cloud_tree(
            BlobObjectStore(args.storage_account_url, args.container),
            CloudRunConfig(
                input_prefix=args.input_prefix,
                output_prefix=args.output_prefix,
                embeddings_name=args.cloud_embeddings_name,
            ),
            config,
        )
        print(f"{args.container}/{args.output_prefix}/tree-manifest.json")
        return 0

    local_values = (args.records, args.embeddings, args.output_dir)
    if not all(local_values):
        raise ValueError("local mode requires --records, --embeddings, and --output-dir")
    result = build_tree(
        InputPaths(
            records=args.records,
            embeddings=args.embeddings,
            embedding_index=args.embedding_index,
            trust_policy=args.trust_policy,
            output_dir=args.output_dir,
        ),
        config,
    )
    print(result.tree_path)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse arguments and dispatch to a track. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.track:
        parser.print_help()
        return 0
    if args.track == "tree":
        return _run_tree(args)
    print(f"evospaice {args.track}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
