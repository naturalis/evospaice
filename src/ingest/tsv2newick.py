#!/usr/bin/env python3

"""Build a taxonomy tree from a BOLD BCDM-TSV dump and write it as Newick.

The script reads a BCDM (Barcode Core Data Model) TSV dump, selects the records
that fall under a given top-level taxon (e.g. 'phylum:Arthropoda'), and folds
the Linnaean ranks of those records into a tree whose root is the top-level
taxon and whose tips are at the requested lowest level ('species', 'subspecies'
or 'BIN'). Empty intermediate ranks are simply skipped, so the tree collapses
where BOLD has no classification. Records without a value at the tip rank are
discarded.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import logging
import os
import sys
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

LOGGER = logging.getLogger("bcdm2tree")

# Linnaean rank columns of the BCDM, from most to least inclusive.
LINNAEAN_RANKS: List[str] = [
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "subfamily",
    "tribe",
    "genus",
    "species",
    "subspecies",
]

# The BIN is not a Linnaean rank but is treated as the terminal level below
# subspecies. It lives in a differently named column, hence the mapping.
BIN_RANK = "BIN"
ALL_RANKS: List[str] = LINNAEAN_RANKS + [BIN_RANK]
COLUMN_FOR_RANK: Dict[str, str] = {rank: rank for rank in LINNAEAN_RANKS}
COLUMN_FOR_RANK[BIN_RANK] = "bin_uri"

# Ranks that may be requested as the tip level.
TIP_RANKS: List[str] = ["species", "subspecies", BIN_RANK]

# Placeholders that BOLD (and its exporters) use for missing values.
NULL_VALUES = frozenset(["", "none", "null", "na", "n/a", "nan", "unknown", "-"])

# Characters that force a Newick label to be quoted.
NEWICK_SPECIALS = frozenset(" \t\n\r()[]{},:;'\"")


class TaxonNode:
    """A node in the taxonomy tree, holding a rank, a name and its children.

    Children are kept in an insertion-ordered dict keyed by (rank, name) so
    that repeated lineages are merged, while homonyms in different parts of the
    tree stay distinct (the key is only unique within one parent). The record
    counter is incremented for every record that terminates at this node.
    """

    __slots__ = ("rank", "name", "children", "records")

    def __init__(self, rank: str, name: str) -> None:
        self.rank = rank
        self.name = name
        self.children: Dict[Tuple[str, str], "TaxonNode"] = {}
        self.records = 0

    def child(self, rank: str, name: str) -> "TaxonNode":
        """Return the child with this rank and name, creating it if needed."""
        key = (rank, name)
        node = self.children.get(key)
        if node is None:
            node = TaxonNode(rank, name)
            self.children[key] = node
        return node

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"TaxonNode({self.rank}={self.name!r}, {len(self.children)} children)"


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Define and parse the command line arguments, returning the namespace."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i", "--infile", required=True,
        help="Location of the BOLD dump in BCDM-TSV format (may be gzipped).",
    )
    parser.add_argument(
        "-t", "--taxon", default="phylum:Arthropoda",
        help="Top-level taxon as 'rank:name' (default: %(default)s).",
    )
    parser.add_argument(
        "-l", "--level", default=BIN_RANK, choices=TIP_RANKS,
        help="Lowest taxonomic level, used for the tips (default: %(default)s).",
    )
    parser.add_argument(
        "-o", "--outfile", default="outfile.tre",
        help="Location of the Newick output file (default: %(default)s).",
    )
    parser.add_argument(
        "-e", "--encoding", default="utf-8",
        help="Character encoding of the input file (default: %(default)s).",
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="Increase verbosity; -v gives DEBUG. Default level is INFO.",
    )
    parser.add_argument(
        "-q", "--quiet", action="count", default=0,
        help="Decrease verbosity; -q gives WARNING, -qq ERROR.",
    )
    return parser.parse_args(argv)


def configure_logging(verbose: int, quiet: int) -> None:
    """Configure the root logger, offsetting INFO by the verbosity flags.

    Every -v lowers the threshold by one logging step (to at most DEBUG) and
    every -q raises it by one (to at most CRITICAL), so plain invocation logs
    at INFO.
    """
    level = logging.INFO - 10 * verbose + 10 * quiet
    level = max(logging.DEBUG, min(logging.CRITICAL, level))
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )
    LOGGER.debug("Logging configured at level %s", logging.getLevelName(level))


def parse_taxon_spec(spec: str) -> Tuple[str, str]:
    """Split a 'rank:name' specification into a validated (rank, name) tuple.

    The rank must be one of the BCDM Linnaean ranks or 'BIN'; the comparison is
    case-insensitive so that 'Phylum:Arthropoda' is accepted as well.
    """
    if ":" not in spec:
        raise ValueError(f"Taxon '{spec}' is not of the form 'rank:name'")
    rank, name = (part.strip() for part in spec.split(":", 1))
    lookup = {candidate.lower(): candidate for candidate in ALL_RANKS}
    if rank.lower() not in lookup:
        raise ValueError(
            f"Unknown rank '{rank}', expected one of: {', '.join(ALL_RANKS)}"
        )
    if not name:
        raise ValueError(f"Taxon '{spec}' has an empty name")
    return lookup[rank.lower()], name


def resolve_rank_path(top_rank: str, tip_rank: str) -> List[str]:
    """Return the ranks strictly below the root, down to and including the tip.

    These are the ranks that are inspected for every record, in order, to
    assemble the lineage that is grafted onto the root.
    """
    top_index = ALL_RANKS.index(top_rank)
    tip_index = ALL_RANKS.index(tip_rank)
    if tip_index <= top_index:
        raise ValueError(
            f"Lowest level '{tip_rank}' is not below top-level rank '{top_rank}'"
        )
    path = ALL_RANKS[top_index + 1 : tip_index + 1]
    LOGGER.debug("Rank path below %s: %s", top_rank, ", ".join(path))
    return path


def open_tsv(location: str, encoding: str):
    """Open a plain or gzipped BCDM-TSV file as a text stream."""
    if location.endswith((".gz", ".gzip")):
        LOGGER.debug("Opening %s as gzip", location)
        return gzip.open(location, mode="rt", encoding=encoding, errors="replace", newline="")
    return open(location, mode="rt", encoding=encoding, errors="replace", newline="")


def iter_records(handle, required: Sequence[str]) -> Iterator[Dict[str, str]]:
    """Yield the rows of a BCDM-TSV stream as dicts, checking required columns.

    Quoting is disabled because BOLD free-text fields (collectors, notes) often
    contain unbalanced quote characters that would otherwise swallow entire
    blocks of the file.
    """
    csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))
    reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
    if reader.fieldnames is None:
        raise ValueError("Input file appears to be empty: no header line found")
    missing = [column for column in required if column not in reader.fieldnames]
    if missing:
        raise ValueError(
            f"Input file lacks required BCDM column(s): {', '.join(missing)}"
        )
    LOGGER.debug("Header has %d columns", len(reader.fieldnames))
    for record in reader:
        yield record


def clean_value(value: Optional[str]) -> Optional[str]:
    """Normalise whitespace in a cell and map placeholder values onto None."""
    if value is None:
        return None
    value = " ".join(value.split())
    if value.lower() in NULL_VALUES:
        return None
    return value


def extract_lineage(record: Dict[str, str], rank_path: Sequence[str]) -> List[Tuple[str, str]]:
    """Collect the (rank, name) pairs a record contributes, skipping blanks.

    Missing intermediate ranks are omitted rather than filled with placeholders,
    so a record with no subfamily attaches its genus directly to the family.
    """
    lineage: List[Tuple[str, str]] = []
    for rank in rank_path:
        name = clean_value(record.get(COLUMN_FOR_RANK[rank]))
        if name is not None:
            lineage.append((rank, name))
    return lineage


def insert_lineage(root: TaxonNode, lineage: Sequence[Tuple[str, str]]) -> TaxonNode:
    """Graft a lineage onto the tree below the root and return the terminal node."""
    node = root
    for rank, name in lineage:
        node = node.child(rank, name)
    node.records += 1
    return node


def build_tree(
    records: Iterator[Dict[str, str]],
    top_rank: str,
    top_name: str,
    rank_path: Sequence[str],
) -> TaxonNode:
    """Fold all records under the top-level taxon into a tree of TaxonNodes.

    Records outside the requested taxon, and records lacking a value at the tip
    rank, are counted and discarded. Progress and rejection tallies are logged.
    """
    root = TaxonNode(top_rank, top_name)
    tip_rank = rank_path[-1]
    column = COLUMN_FOR_RANK[top_rank]
    wanted = top_name.lower()
    seen = kept = off_taxon = no_tip = 0
    for seen, record in enumerate(records, start=1):
        value = clean_value(record.get(column))
        if value is None or value.lower() != wanted:
            off_taxon += 1
            continue
        lineage = extract_lineage(record, rank_path)
        if not lineage or lineage[-1][0] != tip_rank:
            no_tip += 1
            LOGGER.debug("Record %s has no %s", record.get("processid", "?"), tip_rank)
            continue
        insert_lineage(root, lineage)
        kept += 1
        if seen % 1000000 == 0:
            LOGGER.info("Read %d records, kept %d", seen, kept)
    LOGGER.info(
        "Read %d records: kept %d, skipped %d outside %s:%s, skipped %d without %s",
        seen, kept, off_taxon, top_rank, top_name, no_tip, tip_rank,
    )
    return root


def format_label(name: str) -> str:
    """Return a Newick-safe label, quoting and escaping it where necessary."""
    if not name:
        return "''"
    if any(character in NEWICK_SPECIALS for character in name):
        return "'" + name.replace("'", "''") + "'"
    return name


def newick_tokens(root: TaxonNode) -> Iterator[str]:
    """Yield the Newick serialisation of the tree as a stream of small strings.

    Traversal is iterative and streamed so that a full BOLD dump, which can hold
    upwards of a million tips, neither exhausts the recursion limit nor has to
    be assembled into one large string in memory. Internal nodes keep their
    taxon name as a label.
    """
    stack: List[object] = [root]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif item.children:
            yield "("
            pending: List[object] = []
            for child in item.children.values():
                if pending:
                    pending.append(",")
                pending.append(child)
            pending.append(")" + format_label(item.name))
            stack.extend(reversed(pending))
        else:
            yield format_label(item.name)


def write_tree(root: TaxonNode, location: str) -> None:
    """Write the tree to the output location as a single Newick statement."""
    directory = os.path.dirname(os.path.abspath(location))
    if not os.path.isdir(directory):
        raise ValueError(f"Output directory does not exist: {directory}")
    with open(location, mode="wt", encoding="utf-8") as handle:
        for token in newick_tokens(root):
            handle.write(token)
        handle.write(";\n")
    LOGGER.info("Wrote tree to %s", location)


def summarise_tree(root: TaxonNode) -> Tuple[int, int]:
    """Return the number of tips and of internal nodes, logging the tally."""
    tips = internals = 0
    stack = [root]
    while stack:
        node = stack.pop()
        if node.children:
            internals += 1
            stack.extend(node.children.values())
        else:
            tips += 1
    LOGGER.info("Tree has %d tips and %d internal nodes", tips, internals)
    return tips, internals


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the whole pipeline: parse arguments, build the tree, write it out."""
    args = parse_arguments(argv)
    configure_logging(args.verbose, args.quiet)
    try:
        top_rank, top_name = parse_taxon_spec(args.taxon)
        rank_path = resolve_rank_path(top_rank, args.level)
        required = [COLUMN_FOR_RANK[rank] for rank in [top_rank] + rank_path]
        LOGGER.info("Reading %s", args.infile)
        with open_tsv(args.infile, args.encoding) as handle:
            root = build_tree(iter_records(handle, required), top_rank, top_name, rank_path)
    except (ValueError, OSError) as problem:
        LOGGER.error("%s", problem)
        return 1
    if not root.children:
        LOGGER.error("No records matched %s:%s, nothing to write", top_rank, top_name)
        return 1
    summarise_tree(root)
    try:
        write_tree(root, args.outfile)
    except OSError as problem:
        LOGGER.error("%s", problem)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
