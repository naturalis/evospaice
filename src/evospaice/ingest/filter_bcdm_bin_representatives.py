#!/usr/bin/env python3

"""Select one BCDM record per BIN within a target taxon.

The selector favors records that span the chosen primer window, then breaks
ties by distance to the target amplicon length and ambiguity content. What
counts as "best" evidence depends on the primer set (see classify_coverage):
- Primer sets with both a forward and a reverse primer (folmer, zeale) rank a
  genuine "both primers found" match above a forward-only/reverse-only match,
  since only "both" confirms the fragment's true boundaries.
- Forward-only primer sets (leray, elbrecht_bf2) have no reverse boundary by
  design, so a forward match cropped to the end of the read — exactly as
  extract_primer_regions.py does it — is already the best possible evidence.

Input
-----
- BCDM TSV (plain text)

Output
------
- TSV (default): selected rows with sequence replaced by the selected window
- FASTA (optional): one sequence per BIN
- A text report summarizing the run (counts, drop reasons, primer support,
  taxon breakdown) is always written alongside the output.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import statistics
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional

LOGGER = logging.getLogger("filter_bcdm_bin_representatives")

# Placeholder strings BOLD (and its exporters) use for a missing value.
NULL_VALUES = frozenset(["", "none", "null", "na", "n/a", "nan", "unknown", "-"])

# IUPAC degenerate base codes, mapped to the regex character class they match.
IUPAC_MAP = {
    "A": "A",
    "C": "C",
    "G": "G",
    "T": "T",
    "R": "[AG]",
    "Y": "[CT]",
    "S": "[GC]",
    "W": "[AT]",
    "K": "[GT]",
    "M": "[AC]",
    "B": "[CGT]",
    "D": "[AGT]",
    "H": "[ACT]",
    "V": "[ACG]",
    "N": "[ACGT]",
    "I": "[ACGT]",
}

# BCDM Linnaean rank columns, most to least inclusive. Used both to validate
# --taxon and to pick a "child rank" for the taxon breakdown in the report.
BCDM_RANKS: list[str] = [
    "kingdom", "phylum", "class", "order", "family",
    "subfamily", "tribe", "genus", "species", "subspecies",
]


@dataclass(frozen=True)
class PrimerSet:
    """A named forward/reverse primer pair and the amplicon length it targets.

    ``reverse`` may be empty for primer sets that only define a forward primer
    (the window then runs from the forward match to the end of the sequence).
    """

    name: str
    description: str
    forward: str
    reverse: str
    target_length: int
    min_length: int
    max_length: int


PRIMER_SETS: Dict[str, PrimerSet] = {
    # No reverse primer: BOLD COI-5P records rarely retain the jgHCO2198
    # template site intact, so (as in extract_primer_regions.py) we crop from
    # the forward primer to the end of the read and rank by plausible length.
    "leray": PrimerSet(
        name="leray",
        description="Leray/jgLCO1490 forward primer, cropped to end of read, ~313 bp COI mini-barcode.",
        forward="GGWACWGGWTGAACWGTWTAYCCYCC",
        reverse="",
        target_length=313, min_length=280, max_length=400,
    ),
    "folmer": PrimerSet(
        name="folmer",
        description="Folmer LCO1490 + HCO2198, ~658 bp full COI barcode.",
        forward="GGTCAACAAATCATAAAGATATTGG",
        reverse="TAAACTTCAGGGTGACCAAAAAATCA",
        target_length=658, min_length=550, max_length=750,
    ),
    "zeale": PrimerSet(
        name="zeale",
        description="Zeale et al. bat-diet COI fragment, ~157 bp.",
        forward="AGATATTGGAACWTTATATTTTATTTTTGG",
        reverse="WACTAATCAATTWCCAAATCCTCC",
        target_length=157, min_length=130, max_length=200,
    ),
    "elbrecht_bf2": PrimerSet(
        name="elbrecht_bf2",
        description="Elbrecht & Leese BF2 forward primer, cropped to end of read (no reverse boundary).",
        forward="GCHCCHGAYATRGCHTTYCC",
        reverse="",
        target_length=440, min_length=380, max_length=500,
    ),
}


@dataclass(frozen=True)
class SelectionMetrics:
    """Per-sequence facts used to rank candidates within a BIN."""

    primer_support: str
    coverage_rank: int
    window_start: int
    window_end: int
    window_length: int
    ambiguity_count: int
    ambiguity_fraction: float
    distance_to_target: int


@dataclass
class Candidate:
    """One scored BCDM row: its raw fields plus the cropped output sequence."""

    row: Dict[str, str]
    output_sequence: str
    metrics: SelectionMetrics

    @property
    def score_tuple(self) -> tuple:
        """Sort key for picking the best candidate in a BIN (lower is better)."""
        return (
            self.metrics.coverage_rank,
            self.metrics.distance_to_target,
            self.metrics.ambiguity_fraction,
            self.metrics.ambiguity_count,
            -self.metrics.window_length,
        )


def iupac_to_regex(primer: str) -> str:
    """Convert an IUPAC degenerate primer sequence to a regex pattern."""
    return "".join(IUPAC_MAP.get(base, base) for base in primer.upper())


def reverse_complement(seq: str) -> str:
    """Return the reverse complement of a DNA sequence, degenerate bases included."""
    comp = str.maketrans(
        "ACGTRYSWKMBDHVNacgtryswkmbdhvn",
        "TGCAYRSWMKVHDBNtgcayrswmkvhdbn",
    )
    return seq.translate(comp)[::-1]


def clean_value(value: Optional[str]) -> Optional[str]:
    """Collapse whitespace in a cell and map BOLD's placeholder values to None."""
    if value is None:
        return None
    normalized = " ".join(value.split())
    if normalized.lower() in NULL_VALUES:
        return None
    return normalized


def clean_sequence(value: str) -> str:
    """Strip everything but letters from a raw sequence field and upper-case it."""
    return re.sub(r"[^A-Za-z]", "", value).upper()


def parse_taxon_spec(spec: str) -> tuple[str, str]:
    """Split a 'rank:name' spec into a validated (rank, name) pair."""
    if ":" not in spec:
        raise ValueError(f"Taxon '{spec}' must be 'rank:name', e.g. 'phylum:Arthropoda'")
    rank, name = (part.strip() for part in spec.split(":", 1))
    if rank.lower() not in BCDM_RANKS:
        raise ValueError(
            f"Unknown rank '{rank}' in taxon '{spec}'. Expected one of: {', '.join(BCDM_RANKS)}"
        )
    if not name:
        raise ValueError(f"Taxon '{spec}' has an empty name")
    return rank.lower(), name.lower()


def child_rank_of(rank: str) -> Optional[str]:
    """Return the BCDM rank one level below `rank`, or None if it's the last one."""
    index = BCDM_RANKS.index(rank)
    return BCDM_RANKS[index + 1] if index + 1 < len(BCDM_RANKS) else None


def parse_crop_window(spec: str) -> tuple[int, int]:
    """Parse a 'START:END' crop spec (0-based, END exclusive) into a tuple."""
    if ":" not in spec:
        raise ValueError("Crop window must be START:END (0-based, END exclusive)")
    start_text, end_text = spec.split(":", 1)
    start = int(start_text)
    end = int(end_text)
    if start < 0 or end <= start:
        raise ValueError("Crop window must satisfy 0 <= START < END")
    return start, end


def open_tsv(path: Path, encoding: str) -> Iterator[Dict[str, str]]:
    """Yield each row of a BCDM TSV as a dict, tolerating unbalanced quotes."""
    csv.field_size_limit(2**31 - 1)
    with path.open("r", encoding=encoding, errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        if reader.fieldnames is None:
            raise ValueError("Input TSV is empty or missing a header")
        for row in reader:
            yield row


def detect_columns(fieldnames: Iterable[str]) -> dict[str, str]:
    """Resolve the processid/sequence/BIN/marker columns, tolerating naming variants."""
    available = {name.lower(): name for name in fieldnames}

    def pick(required_name: str, options: list[str]) -> str:
        for option in options:
            if option in available:
                return available[option]
        raise ValueError(
            f"Required column '{required_name}' not found. Available columns: {sorted(fieldnames)}"
        )

    return {
        "processid": pick("processid", ["processid"]),
        "sequence": pick("nuc/nucleotides", ["nuc", "nucleotides"]),
        "bin": pick("bin_uri", ["bin_uri", "bin"]),
        "marker": available.get("marker_code", ""),
    }


def compile_primer_patterns(primer_set: PrimerSet) -> tuple[re.Pattern[str], Optional[re.Pattern[str]]]:
    """Build the forward-strand search patterns for a primer set."""
    fwd = re.compile(iupac_to_regex(primer_set.forward), re.IGNORECASE)
    if not primer_set.reverse:
        return fwd, None
    rev_rc = reverse_complement(primer_set.reverse)
    rev = re.compile(iupac_to_regex(rev_rc), re.IGNORECASE)
    return fwd, rev


def classify_coverage(primer_support: str, window_length: int, primer_set: PrimerSet) -> int:
    """Rank how much a match supports a plausible amplicon (lower is better).

    The best achievable evidence depends on whether the primer set defines a
    reverse primer at all:
    - Reverse defined (e.g. folmer, zeale): only a genuine "both" match confirms
      the fragment's true boundaries, so it outranks forward_only/reverse_only,
      which merely guess where the missing boundary would have been.
    - No reverse defined (e.g. leray, elbrecht_bf2): forward_only cropped to the
      end of the read *is* the intended window (as in extract_primer_regions.py),
      so it is the best possible evidence for that primer set.
    """
    plausible = primer_set.min_length <= window_length <= primer_set.max_length
    if primer_set.reverse:
        if primer_support == "both" and plausible:
            return 0
        if primer_support == "both":
            return 1
        if primer_support in {"forward_only", "reverse_only"}:
            return 2
        return 3
    if primer_support == "forward_only" and plausible:
        return 0
    if primer_support == "forward_only":
        return 1
    return 3


def assess_sequence(
    sequence: str,
    fwd_pattern: re.Pattern[str],
    rev_pattern: Optional[re.Pattern[str]],
    primer_set: PrimerSet,
) -> tuple[str, SelectionMetrics]:
    """Locate the primer window in a sequence and score it for BIN-representative ranking."""
    fwd_match = fwd_pattern.search(sequence)
    rev_match = None
    if rev_pattern is not None:
        if fwd_match is not None:
            rev_match = rev_pattern.search(sequence, pos=fwd_match.end())
        if rev_match is None:
            rev_match = rev_pattern.search(sequence)

    if fwd_match is not None and rev_match is not None and rev_match.start() > fwd_match.end():
        window_start = fwd_match.end()
        window_end = rev_match.start()
        primer_support = "both"
    elif fwd_match is not None:
        window_start = fwd_match.end()
        window_end = len(sequence)
        primer_support = "forward_only"
    elif rev_match is not None:
        window_start = 0
        window_end = rev_match.start()
        primer_support = "reverse_only"
    else:
        window_start = 0
        window_end = len(sequence)
        primer_support = "none"

    window_sequence = sequence[window_start:window_end]
    window_length = len(window_sequence)
    ambiguity_count = sum(1 for base in window_sequence if base not in {"A", "C", "G", "T"})
    ambiguity_fraction = ambiguity_count / window_length if window_length else 1.0
    coverage_rank = classify_coverage(primer_support, window_length, primer_set)

    metrics = SelectionMetrics(
        primer_support=primer_support,
        coverage_rank=coverage_rank,
        window_start=window_start,
        window_end=window_end,
        window_length=window_length,
        ambiguity_count=ambiguity_count,
        ambiguity_fraction=ambiguity_fraction,
        distance_to_target=abs(window_length - primer_set.target_length),
    )
    return window_sequence, metrics


def apply_crop(seq: str, crop_window: Optional[tuple[int, int]]) -> str:
    """Apply an optional additional START:END crop on top of the primer window."""
    if crop_window is None:
        return seq
    start, end = crop_window
    if start >= len(seq):
        return ""
    return seq[start:min(end, len(seq))]


def get_rank_value(row: Dict[str, str], rank: str) -> Optional[str]:
    """Look up a taxon rank column case-insensitively and return its cleaned value."""
    for key, value in row.items():
        if key.lower() == rank:
            return clean_value(value)
    return None


def passes_typed_filter(row: Dict[str, str], taxon_rank: str, taxon_name: str) -> bool:
    """Return True if `row` belongs to the requested taxon at the requested rank."""
    value = get_rank_value(row, taxon_rank)
    if value is None:
        return False
    return value.lower() == taxon_name


def write_tsv(
    output_path: Path,
    rows: list[Candidate],
    fieldnames: list[str],
    sequence_column: str,
) -> None:
    """Write selected rows as TSV, with the sequence column replaced by the cropped window."""
    extra_fields = [
        "evospaice_primer_support",
        "evospaice_window_start",
        "evospaice_window_end",
        "evospaice_window_length",
        "evospaice_ambiguities",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            delimiter="\t",
            fieldnames=fieldnames + extra_fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        for cand in rows:
            out_row = dict(cand.row)
            out_row[sequence_column] = cand.output_sequence
            out_row["evospaice_primer_support"] = cand.metrics.primer_support
            out_row["evospaice_window_start"] = str(cand.metrics.window_start)
            out_row["evospaice_window_end"] = str(cand.metrics.window_end)
            out_row["evospaice_window_length"] = str(cand.metrics.window_length)
            out_row["evospaice_ambiguities"] = str(cand.metrics.ambiguity_count)
            writer.writerow(out_row)


def write_fasta(
    output_path: Path,
    rows: list[Candidate],
    processid_col: str,
    marker_col: str,
    bin_col: str,
) -> None:
    """Write one FASTA record per selected BIN representative."""
    with output_path.open("w", encoding="utf-8") as handle:
        for cand in rows:
            processid = clean_value(cand.row.get(processid_col, "")) or "NA"
            marker = clean_value(cand.row.get(marker_col, "")) if marker_col else None
            marker = marker or "NA"
            bin_uri = clean_value(cand.row.get(bin_col, "")) or "NA"
            header = f"BOLD|{processid}|{marker}|{bin_uri}"
            handle.write(f">{header}\n")
            seq = cand.output_sequence
            for i in range(0, len(seq), 80):
                handle.write(seq[i:i + 80] + "\n")


def default_report_path(output_path: Path) -> Path:
    """Return the default report path derived from the output path's stem."""
    return output_path.with_name(f"{output_path.stem}_report.txt")


def generate_report(
    *,
    input_path: Path,
    output_path: Path,
    taxon_rank: str,
    taxon_name: str,
    marker_filter: str,
    primer_set: PrimerSet,
    crop_window: Optional[tuple[int, int]],
    total_rows: int,
    taxon_rows: int,
    drop_counts: Counter,
    bins_seen: int,
    chosen: list[Candidate],
    child_rank: Optional[str],
    child_rank_counts: Counter,
    top_n: int,
) -> str:
    """Build the human-readable text report summarizing one run of the filter."""
    lines: list[str] = []
    lines.append("evospaice BCDM BIN-representative filter report")
    lines.append("=" * 48)
    lines.append(f"Input file:       {input_path}")
    lines.append(f"Output file:      {output_path}")
    lines.append(f"Taxon filter:     {taxon_rank}:{taxon_name}")
    lines.append(f"Marker filter:    {marker_filter or '(none)'}")
    lines.append(f"Primer set:       {primer_set.name} — {primer_set.description}")
    lines.append(
        f"Target length:    {primer_set.target_length} bp "
        f"(spanning range {primer_set.min_length}-{primer_set.max_length} bp)"
    )
    if crop_window is not None:
        lines.append(f"Crop window:      {crop_window[0]}:{crop_window[1]}")
    lines.append("")

    lines.append("Row counts")
    lines.append("-" * 48)
    lines.append(f"Total rows read:              {total_rows}")
    lines.append(f"Rows after taxon/marker filter: {taxon_rows}")
    lines.append(f"Distinct BINs after filter:   {bins_seen}")
    lines.append(f"Selected BIN representatives: {len(chosen)}")
    for reason, count in sorted(drop_counts.items()):
        lines.append(f"  dropped ({reason}): {count}")
    lines.append("")

    support_counts = Counter(cand.metrics.primer_support for cand in chosen)
    lines.append("Primer support among selected representatives")
    lines.append("-" * 48)
    for support in ("both", "forward_only", "reverse_only", "none"):
        lines.append(f"  {support}: {support_counts.get(support, 0)}")
    lines.append("")

    if chosen:
        lengths = [cand.metrics.window_length for cand in chosen]
        ambiguity_fractions = [cand.metrics.ambiguity_fraction for cand in chosen]
        lines.append("Window length (bp)")
        lines.append("-" * 48)
        lines.append(f"  min={min(lengths)} max={max(lengths)} mean={statistics.mean(lengths):.1f}")
        lines.append("")
        lines.append("Ambiguity fraction")
        lines.append("-" * 48)
        lines.append(
            f"  min={min(ambiguity_fractions):.3f} max={max(ambiguity_fractions):.3f} "
            f"mean={statistics.mean(ambiguity_fractions):.3f}"
        )
        lines.append("")

    if child_rank is not None and child_rank_counts:
        lines.append(f"Top {top_n} '{child_rank}' values among filtered rows")
        lines.append("-" * 48)
        for name, count in child_rank_counts.most_common(top_n):
            lines.append(f"  {name}: {count}")
        lines.append("")

    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Input BCDM TSV file")
    parser.add_argument("--output", type=Path, required=True, help="Output path (.tsv or .fasta)")
    parser.add_argument(
        "--taxon",
        default="phylum:Arthropoda",
        help="Higher-taxon filter as 'rank:name'",
    )
    parser.add_argument(
        "--marker-filter",
        default="COI-5P",
        help="Optional marker_code filter (empty string disables)",
    )
    parser.add_argument(
        "--output-format",
        choices=["tsv", "fasta"],
        default="tsv",
    )
    parser.add_argument(
        "--primer-set",
        choices=list(PRIMER_SETS),
        default="leray",
    )
    parser.add_argument("--forward-primer", default=None)
    parser.add_argument("--reverse-primer", default=None)
    parser.add_argument("--target-length", type=int, default=None)
    parser.add_argument("--min-length", type=int, default=None)
    parser.add_argument("--max-length", type=int, default=None)
    parser.add_argument("--crop-window", default="")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--report-top-n", type=int, default=15)
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def resolve_primer_set(args: argparse.Namespace) -> PrimerSet:
    """Apply any --forward-primer/--reverse-primer/--*-length overrides to the chosen primer set."""
    base = PRIMER_SETS[args.primer_set]
    return PrimerSet(
        name=base.name,
        description=base.description,
        forward=args.forward_primer if args.forward_primer is not None else base.forward,
        reverse=args.reverse_primer if args.reverse_primer is not None else base.reverse,
        target_length=args.target_length if args.target_length is not None else base.target_length,
        min_length=args.min_length if args.min_length is not None else base.min_length,
        max_length=args.max_length if args.max_length is not None else base.max_length,
    )


def main() -> None:
    """Filter a BCDM TSV to one primer-window representative per BIN and write TSV/FASTA + report."""
    args = build_parser().parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    taxon_rank, taxon_name = parse_taxon_spec(args.taxon)
    child_rank = child_rank_of(taxon_rank)
    crop_window = parse_crop_window(args.crop_window) if args.crop_window else None
    primer_set = resolve_primer_set(args)
    fwd_pattern, rev_pattern = compile_primer_patterns(primer_set)

    selected_by_bin: dict[str, Candidate] = {}
    bins_seen: set[str] = set()
    child_rank_counts: Counter = Counter()
    drop_counts: Counter = Counter()
    total_rows = 0
    taxon_rows = 0

    fieldnames: Optional[list[str]] = None
    columns: Optional[dict[str, str]] = None

    for row in open_tsv(args.input, encoding=args.encoding):
        total_rows += 1
        if fieldnames is None:
            fieldnames = list(row.keys())
            columns = detect_columns(fieldnames)

        assert columns is not None
        if not passes_typed_filter(row, taxon_rank, taxon_name):
            continue

        if args.marker_filter:
            marker_value = clean_value(row.get(columns["marker"], "")) if columns["marker"] else None
            if marker_value != args.marker_filter:
                continue

        taxon_rows += 1

        if child_rank is not None:
            child_value = get_rank_value(row, child_rank)
            if child_value is not None:
                child_rank_counts[child_value] += 1

        bin_uri = clean_value(row.get(columns["bin"], ""))
        if bin_uri is None:
            drop_counts["missing_bin"] += 1
            continue
        bins_seen.add(bin_uri)

        seq_value = clean_value(row.get(columns["sequence"], ""))
        if seq_value is None:
            drop_counts["missing_sequence"] += 1
            continue

        cleaned_seq = clean_sequence(seq_value)
        if not cleaned_seq:
            drop_counts["empty_after_clean"] += 1
            continue

        primer_window, metrics = assess_sequence(cleaned_seq, fwd_pattern, rev_pattern, primer_set)
        output_seq = apply_crop(primer_window, crop_window)
        if not output_seq:
            drop_counts["empty_after_crop"] += 1
            continue

        candidate = Candidate(row=row, output_sequence=output_seq, metrics=metrics)
        current = selected_by_bin.get(bin_uri)
        if current is None or candidate.score_tuple < current.score_tuple:
            selected_by_bin[bin_uri] = candidate

    if not selected_by_bin:
        raise RuntimeError("No records selected. Check taxon/marker filter and sequence columns.")

    chosen = list(selected_by_bin.values())
    chosen.sort(key=lambda cand: clean_value(cand.row.get(columns["bin"], "")) or "")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output_format == "tsv":
        write_tsv(args.output, chosen, fieldnames or [], columns["sequence"])
    else:
        write_fasta(args.output, chosen, columns["processid"], columns["marker"], columns["bin"])

    report_path = args.report if args.report is not None else default_report_path(args.output)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_text = generate_report(
        input_path=args.input,
        output_path=args.output,
        taxon_rank=taxon_rank,
        taxon_name=taxon_name,
        marker_filter=args.marker_filter,
        primer_set=primer_set,
        crop_window=crop_window,
        total_rows=total_rows,
        taxon_rows=taxon_rows,
        drop_counts=drop_counts,
        bins_seen=len(bins_seen),
        chosen=chosen,
        child_rank=child_rank,
        child_rank_counts=child_rank_counts,
        top_n=args.report_top_n,
    )
    report_path.write_text(report_text, encoding="utf-8")

    support_counts = Counter(cand.metrics.primer_support for cand in chosen)
    LOGGER.info("Read rows: %d", total_rows)
    LOGGER.info("Rows after taxon/marker filter: %d", taxon_rows)
    LOGGER.info("Selected BIN representatives: %d", len(chosen))
    LOGGER.info(
        "Primer support among selected: both=%d, forward_only=%d, reverse_only=%d, none=%d",
        support_counts.get("both", 0),
        support_counts.get("forward_only", 0),
        support_counts.get("reverse_only", 0),
        support_counts.get("none", 0),
    )
    LOGGER.info("Wrote %s", args.output)
    LOGGER.info("Wrote report to %s", report_path)


if __name__ == "__main__":
    main()
