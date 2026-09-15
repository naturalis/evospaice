"""Command-line entry point for evospaice.

This is a stub. It gives every track a home from day one: ``evospaice <track>``
parses, but each subcommand currently reports that it is not yet implemented.
Fill these in as the tracks land — e.g. the ``ingest`` subcommand will front the
BOLD-to-Newick builder now living in ``evospaice.ingest`` (tsv2newick), and
``tree`` will drive the post-order resolve-and-scale pass.

Run it with ``uv run evospaice`` (or ``uv run evospaice --help``).
"""

from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Optional, Sequence

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
    """Build the top-level parser with one placeholder subcommand per track."""
    parser = argparse.ArgumentParser(
        prog="evospaice",
        description="Build a scaled reference tree from barcode embeddings.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="track", metavar="<track>")
    for name, help_text in TRACKS.items():
        subparsers.add_parser(name, help=help_text)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse arguments and dispatch to a track. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.track:
        parser.print_help()
        return 0
    # TODO: dispatch to the track's own entry point as each one lands.
    print(f"evospaice {args.track}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
