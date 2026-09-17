"""Command-line entry point for evospaice.

The ``tree`` subcommands build and evaluate bottom-up trees. The ``validate``
subcommand computes RF and tip-to-root correlation. Other track subcommands
remain placeholders until their implementations are connected.

Run it with ``uv run evospaice`` (or ``uv run evospaice --help``).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("evospaice")
except PackageNotFoundError:  # running from a source checkout that isn't installed
    __version__ = "0.0.0+dev"

# Track -> one-line description, mirrored from the src/evospaice/<track>/README.md files.
# Adding a track here gives it a subcommand automatically.
TRACKS: dict[str, str] = {
    "ingest": "Trim to primer window, dereplicate within taxon, embed records.",
    "tree": "Resolve the backbone bottom-up (NJ) and assign branch lengths.",
    "validate": "Compare trees using RF distance and tip-to-root-correlation.",
    "viz": "Render the scaled tree.",
    "diversity": "Alpha/beta phylogenetic diversity and curation outliers.",
}


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with one subcommand per track."""
    parser = argparse.ArgumentParser(
        prog="evospaice",
        description="Build a scaled reference tree from barcode embeddings.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    subparsers = parser.add_subparsers(dest="track", metavar="<track>")
    for name, help_text in TRACKS.items():
        subparser = subparsers.add_parser(name, help=help_text)
        if name == "tree":
            tree_commands = subparser.add_subparsers(dest="tree_command", metavar="<command>")
            tree_commands.add_parser(
                "build", help="Build a full-taxonomy tree with one of five representations."
            )
            tree_commands.add_parser(
                "compare", help="Compare all five survey representation strategies."
            )
            tree_commands.add_parser(
                "evaluate", help="Evaluate a bottom-up tree against a reference."
            )
            tree_commands.add_parser(
                "explore", help="Create an offline five-method hierarchy explorer in memory."
            )
            tree_commands.add_parser(
                "live", help="Run a localhost merging lab with authenticated live Azure data."
            )
        elif name == "validate":
            from evospaice.validate.evaluate import build_parser as build_validate_parser

            build_validate_parser(subparser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments and dispatch to a track. Returns a process exit code."""
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments and arguments[0] == "validate":
        from evospaice.validate.evaluate import main as validate_main

        return validate_main(arguments[1:])
    if len(arguments) >= 2 and arguments[0] == "tree":
        command, command_arguments = arguments[1], arguments[2:]
        if command == "build":
            from evospaice.tree.centroid import main as build_tree_main

            return build_tree_main(command_arguments)
        if command == "compare":
            from evospaice.tree.compare_representations import main as compare_main

            return compare_main(command_arguments)
        if command == "evaluate":
            from evospaice.validate.whole_tree import main as evaluate_main

            return evaluate_main(command_arguments)
        if command == "explore":
            from evospaice.tree.explore import main as explore_main

            return explore_main(command_arguments)
        if command == "live":
            from evospaice.tree.live import main as live_main

            return live_main(command_arguments)
    parser = build_parser()
    args = parser.parse_args(arguments)
    if not args.track:
        parser.print_help()
        return 0
    # TODO: dispatch to the track's own entry point as each one lands.
    print(f"evospaice {args.track}: not implemented yet", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
