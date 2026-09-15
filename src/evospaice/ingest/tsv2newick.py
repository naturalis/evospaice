#!/usr/bin/env python3

"""Build an annotated BIN tree from a BOLD BCDM-TSV dump and write it as Newick.

The script reads a BCDM (Barcode Core Data Model) TSV dump, selects the records
that fall under a given top-level taxon (e.g. 'phylum:Arthropoda'), and folds
their Linnaean classification into a tree whose tips are unique terminals at the
requested lowest level ('species', 'subspecies' or 'BIN').

Three things happen between reading and writing:

1. Reconciliation. BOLD classifies per record, so the same taxon turns up at
   different depths (a genus with a subfamily in some records and without one in
   others) and occasionally under different parents. Each taxon is assigned one
   canonical parent, so it occurs exactly once at exactly one depth.
2. Merge and lift. A terminal that occurs under several distinct lineages is
   emitted once, attached either at the last common ancestor of those lineages
   or under the lineage holding most records, depending on the placement policy.
   Internal nodes vacated by a lifted terminal are never instantiated.
3. Annotation. Every tip carries its constituent lineages and their record
   counts as a FigTree/BEAST style comment, which DendroPy parses into
   structured annotations and Biopython reads as a comment string.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import fnmatch
import gzip
import logging
import os
import sys
import tarfile
from collections import Counter, defaultdict
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

LOGGER = logging.getLogger("bcdm2tree")

# Linnaean rank columns of the BCDM, from most to least inclusive.
LINNAEAN_RANKS: List[str] = [
    "kingdom", "phylum", "class", "order", "family",
    "subfamily", "tribe", "genus", "species", "subspecies",
]

# The BIN is not a Linnaean rank but is treated as the terminal level below
# subspecies. It lives in a differently named column, hence the mapping.
BIN_RANK = "BIN"
ALL_RANKS: List[str] = LINNAEAN_RANKS + [BIN_RANK]
COLUMN_FOR_RANK: Dict[str, str] = {rank: rank for rank in LINNAEAN_RANKS}
COLUMN_FOR_RANK[BIN_RANK] = "bin_uri"
RANK_INDEX: Dict[str, int] = {rank: index for index, rank in enumerate(ALL_RANKS)}

# Ranks that may be requested as the tip level.
TIP_RANKS: List[str] = ["species", "subspecies", BIN_RANK]

# Placeholders that BOLD (and its exporters) use for missing values.
NULL_VALUES = frozenset(["", "none", "null", "na", "n/a", "nan", "unknown", "-"])

# Characters that force a Newick label to be quoted.
NEWICK_SPECIALS = frozenset(" \t\n\r()[]{},:;'\"")

# Characters that cannot occur inside an annotation value. Square brackets end
# the comment as far as Biopython is concerned; braces and commas delimit list
# values; equals separates key from value.
ANNOTATION_UNSAFE = "[](){},;=\t\r\n"

# Short rank prefixes for the GTDB-flavoured label style. Spelled out rather
# than derived from the rank name, which would collide on subfamily, species
# and subspecies.
RANK_PREFIX: Dict[str, str] = {
    "kingdom": "k", "phylum": "p", "class": "c", "order": "o", "family": "f",
    "subfamily": "sf", "tribe": "t", "genus": "g", "species": "s",
    "subspecies": "ssp", BIN_RANK: "bin",
}

# A taxon is identified by its rank and name; a lineage is a chain of those.
TaxonKey = Tuple[str, str]
Chain = Tuple[TaxonKey, ...]


class TaxonNode:
    """A node in the taxonomy tree, holding a rank, a name and its children.

    Children are kept in an insertion-ordered dict keyed by (rank, name). The
    'records' counter holds the number of records terminating at this node
    before accumulation, and the size of the whole subtree afterwards. The
    'annotation' slot holds the key/value pairs to be serialised, if any.
    """

    __slots__ = ("rank", "name", "children", "records", "annotation")

    def __init__(self, rank: str, name: str) -> None:
        self.rank = rank
        self.name = name
        self.children: Dict[TaxonKey, "TaxonNode"] = {}
        self.records = 0
        self.annotation: Optional[List[Tuple[str, object]]] = None

    def child(self, rank: str, name: str) -> "TaxonNode":
        """Return the child with this rank and name, creating it if needed."""
        key = (rank, name)
        node = self.children.get(key)
        if node is None:
            node = TaxonNode(rank, name)
            self.children[key] = node
        return node

    @property
    def key(self) -> TaxonKey:
        """Return the (rank, name) identity of this node."""
        return (self.rank, self.name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"TaxonNode({self.rank}={self.name!r}, {len(self.children)} children)"


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Define and parse the command line arguments, returning the namespace."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--infile", required=True,
                        help="BOLD dump in BCDM-TSV format (plain, gzipped or in a tar archive).")
    parser.add_argument("-t", "--taxon", default="phylum:Arthropoda",
                        help="Top-level taxon as 'rank:name' (default: %(default)s).")
    parser.add_argument("-l", "--level", default=BIN_RANK, choices=TIP_RANKS,
                        help="Lowest taxonomic level, used for the tips (default: %(default)s).")
    parser.add_argument("-o", "--outfile", default="outfile.tre",
                        help="Newick output file (default: %(default)s).")
    parser.add_argument("-d", "--dissolved", default=None,
                        help="Optional TSV listing taxa that hold no terminal after placement.")
    parser.add_argument("-s", "--sidecar", default=None,
                        help="Optional TSV holding the unmangled lineages and counts per tip.")
    parser.add_argument("-p", "--placement", default="lca", choices=["lca", "plurality"],
                        help="Where to attach a terminal found in several lineages: at their "
                             "last common ancestor, or under the lineage with most records "
                             "(default: %(default)s).")
    parser.add_argument("--max-lift-rank", default="family", choices=ALL_RANKS,
                        help="Warn when a terminal is lifted to this rank or above; such "
                             "lifts usually mean contamination (default: %(default)s).")
    parser.add_argument("--drop-suspect", action="store_true",
                        help="Discard terminals whose lift exceeds --max-lift-rank instead "
                             "of keeping and flagging them.")
    parser.add_argument("--label-style", default="colon", choices=["colon", "gtdb"],
                        help="Internal node labels as 'genus:Vanessa' or 'g__Vanessa' "
                             "(default: %(default)s).")
    parser.add_argument("--writer", default="plain", choices=["plain", "dendropy"],
                        help="Serialise with the built-in streaming writer or via DendroPy; "
                             "output is equivalent, DendroPy costs memory (default: %(default)s).")
    parser.add_argument("-m", "--member", default=None,
                        help="Glob naming the TSV member to read from a tar archive "
                             "(default: the first *.tsv or *.txt file in the archive).")
    parser.add_argument("-e", "--encoding", default="utf-8",
                        help="Character encoding of the input file (default: %(default)s).")
    parser.add_argument("-v", "--verbose", action="count", default=0,
                        help="Increase verbosity; -v gives DEBUG. Default level is INFO.")
    parser.add_argument("-q", "--quiet", action="count", default=0,
                        help="Decrease verbosity; -q gives WARNING, -qq ERROR.")
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
        datefmt="%Y-%m-%dT%H:%M:%S", stream=sys.stderr,
    )
    LOGGER.debug("Logging configured at level %s", logging.getLevelName(level))


def parse_taxon_spec(spec: str) -> TaxonKey:
    """Split a 'rank:name' specification into a validated (rank, name) tuple.

    The rank must be one of the BCDM Linnaean ranks or 'BIN'; the comparison is
    case-insensitive so that 'Phylum:Arthropoda' is accepted as well.
    """
    if ":" not in spec:
        raise ValueError(f"Taxon '{spec}' is not of the form 'rank:name'")
    rank, name = (part.strip() for part in spec.split(":", 1))
    lookup = {candidate.lower(): candidate for candidate in ALL_RANKS}
    if rank.lower() not in lookup:
        raise ValueError(f"Unknown rank '{rank}', expected one of: {', '.join(ALL_RANKS)}")
    if not name:
        raise ValueError(f"Taxon '{spec}' has an empty name")
    return lookup[rank.lower()], name


def resolve_rank_path(top_rank: str, tip_rank: str) -> List[str]:
    """Return the ranks strictly below the root, down to and including the tip."""
    if RANK_INDEX[tip_rank] <= RANK_INDEX[top_rank]:
        raise ValueError(f"Lowest level '{tip_rank}' is not below top-level rank '{top_rank}'")
    path = ALL_RANKS[RANK_INDEX[top_rank] + 1 : RANK_INDEX[tip_rank] + 1]
    LOGGER.debug("Rank path below %s: %s", top_rank, ", ".join(path))
    return path


def open_tar_member(archive: tarfile.TarFile, pattern: Optional[str]):
    """Return a binary stream over the first archive member that looks like the dump.

    The archive is walked in stream order, so only the members up to the match
    are decompressed. Without a pattern the first regular file with a TSV or TXT
    extension is taken, which is how the BOLD data packages are laid out. A
    member that is itself gzipped is unwrapped on the fly.
    """
    for info in archive:
        if not info.isfile():
            continue
        name = os.path.basename(info.name)
        if name.startswith("."):
            continue
        if pattern is not None:
            if not fnmatch.fnmatch(info.name, pattern) and not fnmatch.fnmatch(name, pattern):
                continue
        elif not name.lower().endswith((".tsv", ".txt", ".tsv.gz", ".txt.gz")):
            continue
        LOGGER.info("Reading member %s (%d bytes) from archive", info.name, info.size)
        handle = archive.extractfile(info)
        if handle is None:
            raise ValueError(f"Cannot extract member '{info.name}' from archive")
        return gzip.GzipFile(fileobj=handle) if name.lower().endswith(".gz") else handle
    raise ValueError("No TSV member found in archive; name one explicitly with --member")


def decoded_lines(binary, encoding: str) -> Iterator[str]:
    """Yield decoded lines from a binary stream, tolerating bad byte sequences.

    Used for tar members, which are read as a forward-only stream and therefore
    cannot be wrapped in a TextIOWrapper. The csv module is happy with any
    iterable of strings.
    """
    for line in binary:
        yield line.decode(encoding, errors="replace")


@contextlib.contextmanager
def open_tsv(location: str, encoding: str, member: Optional[str] = None) -> Iterator[Iterable[str]]:
    """Yield an iterable of text lines from a plain, gzipped or tarred BCDM-TSV."""
    lowered = location.lower()
    if lowered.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")):
        LOGGER.debug("Opening %s as tar archive", location)
        with tarfile.open(location, mode="r|*") as archive:
            yield decoded_lines(open_tar_member(archive, member), encoding)
    elif lowered.endswith((".gz", ".gzip")):
        LOGGER.debug("Opening %s as gzip", location)
        with gzip.open(location, mode="rt", encoding=encoding,
                       errors="replace", newline="") as handle:
            yield handle
    else:
        with open(location, mode="rt", encoding=encoding,
                  errors="replace", newline="") as handle:
            yield handle


def iter_records(lines: Iterable[str], required: Sequence[str]) -> Iterator[Dict[str, str]]:
    """Yield the rows of a BCDM-TSV stream as dicts, checking required columns.

    Quoting is disabled because BOLD free-text fields (collectors, notes) often
    contain unbalanced quote characters that would otherwise swallow entire
    blocks of the file.
    """
    csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))
    reader = csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
    if reader.fieldnames is None:
        raise ValueError("Input file appears to be empty: no header line found")
    missing = [column for column in required if column not in reader.fieldnames]
    if missing:
        raise ValueError(f"Input file lacks required BCDM column(s): {', '.join(missing)}")
    LOGGER.debug("Header has %d columns", len(reader.fieldnames))
    for record in reader:
        yield record


def clean_value(value: Optional[str]) -> Optional[str]:
    """Normalise whitespace in a cell and map placeholder values onto None."""
    if value is None:
        return None
    value = " ".join(value.split())
    return None if value.lower() in NULL_VALUES else value


def extract_lineage(record: Dict[str, str], rank_path: Sequence[str]) -> List[TaxonKey]:
    """Collect the (rank, name) pairs a record contributes, skipping blanks.

    Missing intermediate ranks are omitted rather than filled with placeholders;
    the gaps they leave are what reconciliation later repairs.
    """
    lineage: List[TaxonKey] = []
    for rank in rank_path:
        name = clean_value(record.get(COLUMN_FOR_RANK[rank]))
        if name is not None:
            lineage.append((rank, sys.intern(name)))
    return lineage


def build_raw_tree(records: Iterator[Dict[str, str]], root_key: TaxonKey,
                   rank_path: Sequence[str]) -> TaxonNode:
    """Fold all records under the top-level taxon into an unreconciled trie.

    The trie is the compact form of the dump: shared lineage prefixes collapse,
    so a dump of many million records reduces to the few hundred thousand
    distinct paths that reconciliation then works on. Records outside the
    requested taxon, and records without a value at the tip rank, are counted
    and discarded.
    """
    root = TaxonNode(*root_key)
    tip_rank = rank_path[-1]
    column = COLUMN_FOR_RANK[root_key[0]]
    wanted = root_key[1].lower()
    seen = kept = off_taxon = no_tip = 0
    for seen, record in enumerate(records, start=1):
        if seen % 1000000 == 0:
            LOGGER.info("Read %d records, kept %d", seen, kept)
        value = clean_value(record.get(column))
        if value is None or value.lower() != wanted:
            off_taxon += 1
            continue
        lineage = extract_lineage(record, rank_path)
        if not lineage or lineage[-1][0] != tip_rank:
            no_tip += 1
            continue
        node = root
        for rank, name in lineage:
            node = node.child(rank, name)
        node.records += 1
        kept += 1
    LOGGER.info("Read %d records: kept %d, skipped %d outside %s:%s, skipped %d without %s",
                seen, kept, off_taxon, root_key[0], root_key[1], no_tip, tip_rank)
    return root


def accumulate_counts(root: TaxonNode) -> None:
    """Turn per-node record counts into subtree totals, bottom up, iteratively."""
    order: List[TaxonNode] = []
    stack = [root]
    while stack:
        node = stack.pop()
        order.append(node)
        stack.extend(node.children.values())
    for node in reversed(order):
        node.records += sum(child.records for child in node.children.values())
    LOGGER.debug("Accumulated %d records over %d nodes", root.records, len(order))


def collect_parent_votes(root: TaxonNode, tip_rank: str) -> Tuple[
        Dict[TaxonKey, Counter], Dict[TaxonKey, Counter]]:
    """Tally, for every taxon, which parent taxa it was observed under.

    Walks the raw trie and votes with subtree record counts, so a lineage seen
    in ten thousand records outweighs one seen twice. Internal taxa and
    terminals are tallied separately: internal taxa are reconciled to a single
    parent, whereas terminals keep all their candidates for the placement step.
    """
    internal: Dict[TaxonKey, Counter] = defaultdict(Counter)
    tips: Dict[TaxonKey, Counter] = defaultdict(Counter)
    stack: List[Tuple[TaxonNode, TaxonKey]] = [(child, root.key) for child in root.children.values()]
    while stack:
        node, parent_key = stack.pop()
        target = tips if node.rank == tip_rank else internal
        target[node.key][parent_key] += node.records
        for child in node.children.values():
            stack.append((child, node.key))
    LOGGER.info("Found %d distinct internal taxa and %d distinct terminals",
                len(internal), len(tips))
    return internal, tips


def choose_parent(taxon: TaxonKey, votes: Counter) -> TaxonKey:
    """Pick one canonical parent for a taxon from its observed candidates.

    The deepest candidate wins, so a genus recorded with a subfamily in some
    records and without one in others is placed under the subfamily. Candidates
    at that same deepest rank are a genuine classification conflict rather than
    mere patchiness, so the most-supported one wins and the clash is logged.
    """
    deepest = max(RANK_INDEX[rank] for rank, _ in votes)
    contenders = {key: count for key, count in votes.items() if RANK_INDEX[key[0]] == deepest}
    if len(contenders) > 1:
        rendered = ", ".join(f"{name} ({count})" for (_, name), count
                             in sorted(contenders.items(), key=lambda item: -item[1]))
        LOGGER.warning("%s %s has conflicting %s assignments: %s",
                       taxon[0], taxon[1], ALL_RANKS[deepest], rendered)
    return max(sorted(contenders), key=lambda key: contenders[key])


def reconcile_taxonomy(internal: Dict[TaxonKey, Counter], root_key: TaxonKey) -> Dict[TaxonKey, Chain]:
    """Give every internal taxon one canonical lineage from the root down to it.

    Taxa are resolved from the most to the least inclusive rank, so a taxon's
    parent already has a chain by the time the taxon itself is resolved. Because
    a parent always sits at a strictly higher rank, the result is guaranteed to
    be a tree rather than a graph with cycles.
    """
    chains: Dict[TaxonKey, Chain] = {root_key: (root_key,)}
    patched = conflicted = 0
    for taxon in sorted(internal, key=lambda key: RANK_INDEX[key[0]]):
        votes = internal[taxon]
        depths = {RANK_INDEX[rank] for rank, _ in votes}
        if len(depths) > 1:
            patched += 1
        if sum(1 for key in votes if RANK_INDEX[key[0]] == max(depths)) > 1:
            conflicted += 1
        parent = choose_parent(taxon, votes)
        parent_chain = chains.get(parent)
        if parent_chain is None:
            LOGGER.debug("Parent %s of %s was not reconciled, attaching to root", parent, taxon)
            parent_chain = (root_key,)
        chains[taxon] = parent_chain + (taxon,)
    LOGGER.info("Reconciled %d taxa: %d were recorded at more than one depth, "
                "%d had rival parents at the same rank", len(internal), patched, conflicted)
    distribution = Counter(len(chain) for chain in chains.values())
    LOGGER.debug("Depth distribution %s", dict(sorted(distribution.items())))
    return chains


def drop_redundant_candidates(candidates: Dict[TaxonKey, int],
                              chains: Dict[TaxonKey, Chain]) -> Dict[TaxonKey, int]:
    """Remove candidate parents that are merely less resolved than another one.

    A terminal recorded under both 'Vanessa' and 'Vanessa atalanta' is not in
    conflict with itself: the first lineage is a prefix of the second and only
    reflects a record that was never identified to species. Folding the prefix
    into its extension keeps such patchiness from triggering a lift.
    """
    keys = [key for key in candidates if key in chains]
    kept: Dict[TaxonKey, int] = {}
    for key in keys:
        chain = chains[key]
        extensions = [other for other in keys
                      if other != key and chains[other][:len(chain)] == chain]
        if not extensions:
            kept[key] = candidates[key]
    if len(kept) == 1 and len(keys) > 1:
        only = next(iter(kept))
        kept[only] = sum(candidates[key] for key in keys)
    return kept or {key: candidates[key] for key in keys}


def last_common_ancestor(chains_in: Sequence[Chain]) -> Chain:
    """Return the longest lineage prefix shared by all the given lineages."""
    shortest = min(len(chain) for chain in chains_in)
    common = 0
    while common < shortest and len({chain[common] for chain in chains_in}) == 1:
        common += 1
    return chains_in[0][:common]


def place_terminal(candidates: Dict[TaxonKey, int], chains: Dict[TaxonKey, Chain],
                   policy: str) -> Tuple[Chain, bool]:
    """Decide where a terminal attaches, returning its lineage and whether it was lifted.

    With a single candidate parent the terminal simply hangs below it. With
    several, the 'lca' policy attaches it at their last common ancestor, which
    is honest about the conflict but costs resolution, whereas 'plurality'
    attaches it under the best supported candidate, which keeps the tree
    rank-consistent at the price of hiding the minority lineages.
    """
    resolved = drop_redundant_candidates(candidates, chains)
    if len(resolved) == 1:
        return chains[next(iter(resolved))], False
    if policy == "plurality":
        winner = max(sorted(resolved), key=lambda key: resolved[key])
        return chains[winner], False
    return last_common_ancestor([chains[key] for key in sorted(resolved)]), True


def sanitise_value(value: object) -> str:
    """Replace characters that a Newick comment or a list value cannot hold."""
    return "".join("_" if character in ANNOTATION_UNSAFE else character
                   for character in str(value))


def normalise_fields(fields: Sequence[Tuple[str, object]]) -> List[Tuple[str, object]]:
    """Sanitise annotation values and collapse one-element lists into scalars.

    DendroPy's metadata parser mishandles a brace list holding a single item:
    it swallows the closing brace and the field that follows it, silently
    corrupting both. Emitting such values as bare scalars avoids the trap, at
    the cost of a consumer having to accept either a string or a list.
    """
    normalised: List[Tuple[str, object]] = []
    for key, value in fields:
        if isinstance(value, (list, tuple)):
            items = [sanitise_value(item) for item in value]
            normalised.append((key, items[0] if len(items) == 1 else items))
        else:
            normalised.append((key, sanitise_value(value)))
    return normalised


def format_annotation(fields: Sequence[Tuple[str, object]]) -> str:
    """Render key/value pairs as a FigTree/BEAST style Newick comment.

    Lists become brace-delimited so that DendroPy reads them back as Python
    lists. NHX is deliberately not used: its field separator is the colon, which
    occurs in every rank-prefixed name and in every BIN URI, and both DendroPy
    and Biopython silently mangle such values.
    """
    parts: List[str] = []
    for key, value in normalise_fields(fields):
        rendered = "{" + ",".join(value) + "}" if isinstance(value, list) else value
        parts.append(f"{key}={rendered}")
    return "&" + ",".join(parts)


def describe_taxon(key: TaxonKey, style: str) -> str:
    """Render a (rank, name) pair as a label in the requested style."""
    rank, name = key
    if style == "gtdb":
        return f"{RANK_PREFIX[rank]}__{name.replace(' ', '_')}"
    return f"{rank}:{name}"


def build_annotation(terminal: TaxonKey, candidates: Dict[TaxonKey, int], attachment: Chain,
                     lifted: bool, suspect: bool, style: str) -> List[Tuple[str, object]]:
    """Assemble the annotation comment for one terminal.

    Records the rank, the parent lineages the terminal was seen under with their
    record counts in matching order, where it ended up, and whether the
    placement was a lift or a suspicious one.
    """
    ordered = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
    fields: List[Tuple[str, object]] = [
        ("rank", terminal[0]),
        ("records", sum(candidates.values())),
        ("n_lineages", len(ordered)),
        ("taxa", [describe_taxon(key, style) for key, _ in ordered]),
        ("counts", [count for _, count in ordered]),
        ("placed_at", describe_taxon(attachment[-1], style) if attachment else "root"),
    ]
    if lifted:
        fields.append(("lifted", "yes"))
    if suspect:
        fields.append(("suspect", "yes"))
    return fields


def graft(root: TaxonNode, chain: Chain, terminal: TaxonKey,
          annotation: List[Tuple[str, object]], records: int) -> None:
    """Instantiate a terminal's lineage below the root and hang the terminal on it.

    Only lineages that actually carry a terminal are created, so internal nodes
    vacated by a lifted terminal never come into existence and no pruning pass
    is needed.
    """
    node = root
    for rank, name in chain[1:]:
        node = node.child(rank, name)
    tip = node.child(*terminal)
    tip.annotation = annotation
    tip.records = records


def build_final_tree(tips: Dict[TaxonKey, Counter], chains: Dict[TaxonKey, Chain],
                     root_key: TaxonKey, args: argparse.Namespace) -> Tuple[TaxonNode, List[dict]]:
    """Place every terminal and assemble the reconciled tree, with a placement log.

    Returns the tree and one dict per terminal describing where it went, which
    is what the sidecar TSV is written from and what the summary is counted
    over.
    """
    root = TaxonNode(*root_key)
    limit = RANK_INDEX[args.max_lift_rank]
    placements: List[dict] = []
    dropped = 0
    for terminal in sorted(tips):
        candidates = dict(tips[terminal])
        attachment, lifted = place_terminal(candidates, chains, args.placement)
        if not attachment:
            attachment = (root_key,)
        suspect = lifted and RANK_INDEX[attachment[-1][0]] <= limit
        if suspect:
            LOGGER.warning("%s %s lifted to %s:%s over %d lineages",
                           terminal[0], terminal[1], attachment[-1][0],
                           attachment[-1][1], len(candidates))
            if args.drop_suspect:
                dropped += 1
                continue
        annotation = build_annotation(terminal, candidates, attachment,
                                      lifted, suspect, args.label_style)
        graft(root, attachment, terminal, annotation, sum(candidates.values()))
        placements.append({"terminal": terminal, "attachment": attachment, "lifted": lifted,
                           "suspect": suspect, "candidates": candidates})
    if dropped:
        LOGGER.info("Dropped %d suspect terminal(s)", dropped)
    return root, placements


def summarise_placements(placements: Sequence[dict]) -> None:
    """Log how many terminals were lifted, to which ranks, and how many are suspect."""
    lifted = [item for item in placements if item["lifted"]]
    suspect = sum(1 for item in placements if item["suspect"])
    LOGGER.info("Placed %d terminals: %d unambiguous, %d lifted (%d suspect)",
                len(placements), len(placements) - len(lifted), len(lifted), suspect)
    if lifted:
        histogram = Counter(item["attachment"][-1][0] for item in lifted)
        ordered = sorted(histogram.items(), key=lambda item: RANK_INDEX[item[0]])
        LOGGER.info("Lift targets: %s", ", ".join(f"{rank}={count}" for rank, count in ordered))


def format_label(name: str) -> str:
    """Return a Newick-safe label, quoting and escaping it where necessary."""
    if not name:
        return "''"
    if any(character in NEWICK_SPECIALS for character in name):
        return "'" + name.replace("'", "''") + "'"
    return name


def node_label(node: TaxonNode, root_key: TaxonKey, style: str) -> str:
    """Return a node's unquoted label: rank-prefixed internally, bare for tips.

    Terminals keep their raw name, since a BIN URI or a binomial is already
    unique and downstream tools match on it directly; their rank travels in the
    annotation instead. Quoting is left to whichever writer consumes this.
    """
    if not node.children and node.key != root_key:
        return node.name
    return describe_taxon(node.key, style)


def newick_tokens(root: TaxonNode, style: str) -> Iterator[str]:
    """Yield the Newick serialisation of the tree as a stream of small strings.

    Traversal is iterative and streamed so that a full BOLD dump, which holds
    upwards of a million terminals, neither exhausts the recursion limit nor has
    to be assembled into one large string in memory.
    """
    root_key = root.key
    stack: List[object] = [root]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
            continue
        label = format_label(node_label(item, root_key, style))
        suffix = f"[{format_annotation(item.annotation)}]" if item.annotation else ""
        if item.children:
            yield "("
            pending: List[object] = []
            for child in item.children.values():
                if pending:
                    pending.append(",")
                pending.append(child)
            pending.append(")" + label + suffix)
            stack.extend(reversed(pending))
        else:
            yield label + suffix


def write_tree_plain(root: TaxonNode, location: str, style: str) -> None:
    """Stream the tree to the output location as a single Newick statement."""
    with open(location, mode="wt", encoding="utf-8") as handle:
        for token in newick_tokens(root, style):
            handle.write(token)
        handle.write(";\n")
    LOGGER.info("Wrote tree to %s", location)


def write_tree_dendropy(root: TaxonNode, location: str, style: str) -> None:
    """Convert the tree to a DendroPy object and let DendroPy serialise it.

    Annotations are attached as first-class DendroPy annotations rather than raw
    comments, so the written file is guaranteed to round-trip into
    node.annotations. This costs roughly twenty times the memory of the
    streaming writer, so it is not the default.
    """
    import dendropy

    tree = dendropy.Tree()
    stack = [(root, tree.seed_node)]
    while stack:
        source, target = stack.pop()
        label = node_label(source, root.key, style)
        if source.children:
            target.label = label
        else:
            target.taxon = tree.taxon_namespace.new_taxon(label)
        for key, value in normalise_fields(source.annotation or []):
            target.annotations.add_new(key, value)
        for child in source.children.values():
            stack.append((child, target.new_child()))
    tree.write(path=location, schema="newick", suppress_rooting=True,
               suppress_edge_lengths=True, suppress_annotations=False,
               annotations_as_nhx=False, suppress_internal_node_labels=False)
    LOGGER.info("Wrote tree to %s via DendroPy", location)


def write_sidecar(placements: Sequence[dict], location: str, style: str) -> None:
    """Write the per-terminal lineages and record counts as a TSV.

    Holds the unmangled names, unlike the Newick annotation, whose values have
    to give up commas and brackets to stay parseable.
    """
    with open(location, mode="wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["terminal", "rank", "placed_at", "lifted", "suspect",
                         "n_lineages", "records", "lineages", "counts"])
        for item in placements:
            ordered = sorted(item["candidates"].items(), key=lambda pair: (-pair[1], pair[0]))
            writer.writerow([
                item["terminal"][1], item["terminal"][0],
                describe_taxon(item["attachment"][-1], style),
                "yes" if item["lifted"] else "no", "yes" if item["suspect"] else "no",
                len(ordered), sum(count for _, count in ordered),
                "|".join(describe_taxon(key, style) for key, _ in ordered),
                "|".join(str(count) for _, count in ordered),
            ])
    LOGGER.info("Wrote %d terminal lineages to %s", len(placements), location)


def dissolved_taxa(root: TaxonNode, chains: Dict[TaxonKey, Chain]) -> List[TaxonKey]:
    """Return the reconciled taxa that no longer appear anywhere in the tree.

    These are taxa every terminal of which was lifted past them, so their names
    survive only inside tip annotations. Computed against the instantiated tree
    rather than against placement targets, since a taxon also stays alive by
    holding another taxon that holds a terminal.
    """
    alive = set()
    stack = [root]
    while stack:
        node = stack.pop()
        alive.add(node.key)
        stack.extend(node.children.values())
    return [key for key in chains if key not in alive]


def report_dissolved(taxa: Sequence[TaxonKey], chains: Dict[TaxonKey, Chain],
                     total: int, location: Optional[str]) -> None:
    """Log the rank breakdown of dissolved taxa and optionally write them out."""
    if not taxa:
        return
    histogram = Counter(rank for rank, _ in taxa)
    ordered = sorted(histogram.items(), key=lambda item: RANK_INDEX[item[0]])
    LOGGER.info("%d of %d reconciled taxa (%.1f%%) hold no terminal after placement "
                "and survive only in tip annotations: %s", len(taxa), total,
                100.0 * len(taxa) / max(total, 1),
                ", ".join(f"{rank}={count}" for rank, count in ordered))
    if location is None:
        return
    with open(location, mode="wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["rank", "name", "lineage"])
        for key in sorted(taxa, key=lambda item: (RANK_INDEX[item[0]], item[1])):
            writer.writerow([key[0], key[1], "|".join(name for _, name in chains[key])])
    LOGGER.info("Wrote %d dissolved taxa to %s", len(taxa), location)


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
    """Run the pipeline: read, reconcile, place, annotate and write."""
    args = parse_arguments(argv)
    configure_logging(args.verbose, args.quiet)
    try:
        root_key = parse_taxon_spec(args.taxon)
        rank_path = resolve_rank_path(root_key[0], args.level)
        required = [COLUMN_FOR_RANK[rank] for rank in [root_key[0]] + rank_path]
        LOGGER.info("Reading %s", args.infile)
        with open_tsv(args.infile, args.encoding, args.member) as lines:
            raw = build_raw_tree(iter_records(lines, required), root_key, rank_path)
        if not raw.children:
            raise ValueError(f"No records matched {root_key[0]}:{root_key[1]}")
        accumulate_counts(raw)
        internal, tips = collect_parent_votes(raw, args.level)
        chains = reconcile_taxonomy(internal, root_key)
        del raw
        tree, placements = build_final_tree(tips, chains, root_key, args)
        if not tree.children:
            raise ValueError("Every terminal was dropped, nothing to write")
        summarise_placements(placements)
        summarise_tree(tree)
        report_dissolved(dissolved_taxa(tree, chains), chains, len(chains), args.dissolved)
        if args.writer == "dendropy":
            write_tree_dendropy(tree, args.outfile, args.label_style)
        else:
            write_tree_plain(tree, args.outfile, args.label_style)
        if args.sidecar:
            write_sidecar(placements, args.sidecar, args.label_style)
    except (ValueError, OSError, EOFError, ImportError, tarfile.TarError) as problem:
        LOGGER.error("%s", problem)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())