"""Command-line dispatch for diversity, validation, and remaining track placeholders."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

from dendropy.utility.error import DataParseError

try:
    __version__ = version("evospaice")
except PackageNotFoundError:  # running from a source checkout that isn't installed
    __version__ = "0.0.0+dev"

# Track -> one-line description, mirrored from the src/evospaice/<track>/README.md files.
# Adding a track here gives it a subcommand automatically.
TRACKS: dict[str, str] = {
    "ingest": "Trim to primer window, dereplicate within taxon, embed records.",
    "tree": "Resolve the backbone bottom-up (NJ) and assign branch lengths.",
    "validate": "Compare inferred trees and evaluate embedding distance fidelity.",
    "viz": "Render the scaled tree.",
    "diversity": "Alpha/beta phylogenetic diversity and curation outliers.",
}


def build_parser() -> argparse.ArgumentParser:
    """Build track parsers using their existing package argument definitions."""
    parser = argparse.ArgumentParser(
        prog="evospaice",
        description="Build a scaled reference tree from barcode embeddings.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="track", metavar="<track>")
    for name, help_text in TRACKS.items():
        child = subparsers.add_parser(name, help=help_text)
        if name == "diversity":
            from evospaice.diversity.evaluate import build_parser as configure
            from evospaice.diversity.evaluate import run
        elif name == "validate":
            from evospaice.validate.evaluate import build_parser as configure
            from evospaice.validate.evaluate import run
        else:
            continue
        configure(child)
        child.set_defaults(handler=run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to a track. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.track:
        parser.print_help()
        return 0
    if hasattr(args, "handler"):
        try:
            return args.handler(args)
        except (ValueError, KeyError, DataParseError) as error:
            parser.error(str(error))
        except OSError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            return 130
    print(f"evospaice {args.track}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
