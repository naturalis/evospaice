#!/usr/bin/env python3

"""Select one BCDM record per BIN within a target taxon.

The selector favors records that span the chosen primer window, then breaks
ties by closeness to the target amplicon length and ambiguity content. What
counts as "best" evidence depends on the primer set (see classify_coverage):
- Primer sets with both a forward and a reverse primer (folmer, zeale) rank a
  genuine "both primers found" match above a forward-only/reverse-only match,
  since only "both" confirms the fragment's true boundaries.
- Forward-only primer sets (leray, elbrecht_bf2) have no reverse boundary by
  design, so a forward match cropped to the end of the read — exactly as
  extract_primer_regions.py does it — is already the best possible evidence.
- No primer match at all ("none") is always the lowest tier and its "window"
  is the *entire* raw sequence, since there is no primer-defined boundary. So
  the usual "closest to target length" tie-break would be meaningless there
  (a length is not evidence of the right region) — for "none" candidates the
  tie-break instead prefers the *longer* sequence (more information, more
  likely to actually contain the target region even without a clean primer
  hit), then fewer ambiguities.
- Primer search tries an exact IUPAC match first, then falls back to a
  mismatch-tolerant seed-and-extend search (--max-primer-mismatches) so a
  single sequencing error/SNP in the primer site doesn't sink a record all
  the way to "none". An exact match still outranks a mismatched one within
  the same coverage tier.

Quality gates (--min-sequence-length, --max-ambiguity-fraction) are opt-in
hard rejections applied before a candidate can win its BIN; unlike the
primer-window scoring above, which only deprioritizes a poor candidate, these
can make a BIN disappear entirely from the output if every one of its records
fails the gate. Off by default so existing behaviour is unchanged.

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

# IUPAC degenerate base codes, mapped to the literal bases they stand for.
# Used both to build the regex character class for exact search and, base by
# base, to count mismatches for the fuzzy fallback search.
IUPAC_BASES: Dict[str, frozenset[str]] = {
    "A": frozenset("A"),
    "C": frozenset("C"),
    "G": frozenset("G"),
    "T": frozenset("T"),
    "R": frozenset("AG"),
    "Y": frozenset("CT"),
    "S": frozenset("GC"),
    "W": frozenset("AT"),
    "K": frozenset("GT"),
    "M": frozenset("AC"),
    "B": frozenset("CGT"),
    "D": frozenset("AGT"),
    "H": frozenset("ACT"),
    "V": frozenset("ACG"),
    "N": frozenset("ACGT"),
    "I": frozenset("ACGT"),
}

# Regex character class per IUPAC code, derived from IUPAC_BASES.
IUPAC_MAP: Dict[str, str] = {
    base: (next(iter(letters)) if len(letters) == 1 else "[" + "".join(sorted(letters)) + "]")
    for base, letters in IUPAC_BASES.items()
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
    primer_mismatches: int
    coverage_rank: int
    window_start: int
    window_end: int
    window_length: int
    ambiguity_count: int
    ambiguity_fraction: float
    # Second tie-break key (lower is better). For a primer-anchored window
    # (both/forward_only/reverse_only) this is distance to the target length —
    # a real quality signal, since the window boundary is primer-evidenced.
    # For "none" (no primer evidence at all, window = whole sequence) it is
    # -window_length instead, so the *longer* sequence wins rather than
    # whichever raw length coincidentally sits closest to the target.
    tiebreak_length: int


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
            self.metrics.primer_mismatches,
            self.metrics.tiebreak_length,
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


@dataclass(frozen=True)
class PrimerMatch:
    """One located primer occurrence."""

    start: int
    end: int
    mismatches: int


@dataclass(frozen=True)
class FuzzyPrimer:
    """A primer's per-position allowed bases plus precomputed exact-seed patterns.

    Search uses seed-and-extend: split the primer into (max_mismatches + 1)
    contiguous chunks and exact-search each with a fast compiled regex. By the
    pigeonhole principle, any alignment with at most `max_mismatches`
    mismatches must have at least one mismatch-free chunk, so every valid
    alignment is found via one of the chunk hits; each candidate anchor is
    then verified base-by-base (cheap, since there are few candidates).
    """

    base_sets: tuple[frozenset[str], ...]
    length: int
    max_mismatches: int
    seed_patterns: tuple[re.Pattern[str], ...]
    seed_offsets: tuple[int, ...]


def compile_fuzzy_primer(primer: str, max_mismatches: int) -> FuzzyPrimer:
    """Precompute the seed patterns and base sets used for mismatch-tolerant search."""
    base_sets = tuple(IUPAC_BASES.get(base, frozenset(base)) for base in primer.upper())
    length = len(base_sets)
    n_chunks = max_mismatches + 1
    chunk_len = max(1, length // n_chunks)
    seed_patterns: list[re.Pattern[str]] = []
    seed_offsets: list[int] = []
    offset = 0
    for i in range(n_chunks):
        if offset >= length:
            break
        end = length if i == n_chunks - 1 else min(length, offset + chunk_len)
        chunk = primer[offset:end]
        seed_patterns.append(re.compile(iupac_to_regex(chunk), re.IGNORECASE))
        seed_offsets.append(offset)
        offset = end
    return FuzzyPrimer(base_sets, length, max_mismatches, tuple(seed_patterns), tuple(seed_offsets))


def _count_mismatches(
    sequence: str, anchor: int, base_sets: tuple[frozenset[str], ...], limit: int
) -> Optional[int]:
    """Mismatches between sequence[anchor:anchor+len(base_sets)] and base_sets, or None if out of bounds/over limit."""
    length = len(base_sets)
    if anchor < 0 or anchor + length > len(sequence):
        return None
    mismatches = 0
    for i in range(length):
        if sequence[anchor + i].upper() not in base_sets[i]:
            mismatches += 1
            if mismatches > limit:
                return None
    return mismatches


def fuzzy_search(sequence: str, primer: FuzzyPrimer, pos: int = 0) -> Optional[PrimerMatch]:
    """Leftmost mismatch-tolerant occurrence of `primer` in `sequence` at/after `pos`."""
    candidate_anchors: set[int] = set()
    for pattern, seed_offset in zip(primer.seed_patterns, primer.seed_offsets):
        for hit in pattern.finditer(sequence, pos):
            candidate_anchors.add(hit.start() - seed_offset)

    best: Optional[PrimerMatch] = None
    for anchor in sorted(a for a in candidate_anchors if a >= pos):
        mismatches = _count_mismatches(sequence, anchor, primer.base_sets, primer.max_mismatches)
        if mismatches is not None:
            best = PrimerMatch(start=anchor, end=anchor + primer.length, mismatches=mismatches)
            break  # anchors are sorted ascending, so the first valid one is leftmost
    return best


@dataclass(frozen=True)
class CompiledPrimer:
    """An exact-match regex plus an optional mismatch-tolerant fallback for one primer."""

    exact: re.Pattern[str]
    fuzzy: Optional[FuzzyPrimer]


def find_primer(compiled: CompiledPrimer, sequence: str, pos: int = 0) -> Optional[PrimerMatch]:
    """Find `compiled`'s primer at/after `pos`: exact match first, fuzzy fallback if that fails.

    An exact hit anywhere in the sequence is preferred over a fuzzy hit even
    if the fuzzy hit would start earlier — exact primer evidence outranks an
    approximate one (mirrored in Candidate.score_tuple's mismatch tie-break).
    """
    exact = compiled.exact.search(sequence, pos)
    if exact is not None:
        return PrimerMatch(start=exact.start(), end=exact.end(), mismatches=0)
    if compiled.fuzzy is None:
        return None
    return fuzzy_search(sequence, compiled.fuzzy, pos)


def compile_primer_patterns(
    primer_set: PrimerSet, max_mismatches: int = 0
) -> tuple[CompiledPrimer, Optional[CompiledPrimer]]:
    """Build the forward-strand search patterns for a primer set."""

    def compile_one(primer: str) -> CompiledPrimer:
        exact = re.compile(iupac_to_regex(primer), re.IGNORECASE)
        fuzzy = compile_fuzzy_primer(primer, max_mismatches) if max_mismatches > 0 else None
        return CompiledPrimer(exact=exact, fuzzy=fuzzy)

    fwd = compile_one(primer_set.forward)
    if not primer_set.reverse:
        return fwd, None
    rev = compile_one(reverse_complement(primer_set.reverse))
    return fwd, rev


def classify_coverage(primer_support: str, window_length: int, primer_set: PrimerSet) -> int:
    """Rank how much a match supports a plausible amplicon (lower is better)."""
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
    fwd_primer: CompiledPrimer,
    rev_primer: Optional[CompiledPrimer],
    primer_set: PrimerSet,
) -> tuple[str, SelectionMetrics]:
    """Locate the primer window in a sequence and score it for BIN-representative ranking."""
    fwd_match = find_primer(fwd_primer, sequence)
    rev_match = None
    if rev_primer is not None:
        if fwd_match is not None:
            rev_match = find_primer(rev_primer, sequence, pos=fwd_match.end)
        if rev_match is None:
            rev_match = find_primer(rev_primer, sequence)

    if fwd_match is not None and rev_match is not None and rev_match.start > fwd_match.end:
        window_start = fwd_match.end
        window_end = rev_match.start
        primer_support = "both"
        primer_mismatches = fwd_match.mismatches + rev_match.mismatches
    elif fwd_match is not None:
        window_start = fwd_match.end
        window_end = len(sequence)
        primer_support = "forward_only"
        primer_mismatches = fwd_match.mismatches
    elif rev_match is not None:
        window_start = 0
        window_end = rev_match.start
        primer_support = "reverse_only"
        primer_mismatches = rev_match.mismatches
    else:
        window_start = 0
        window_end = len(sequence)
        primer_support = "none"
        primer_mismatches = 0

    window_sequence = sequence[window_start:window_end]
    window_length = len(window_sequence)
    ambiguity_count = sum(1 for base in window_sequence if base not in {"A", "C", "G", "T"})
    ambiguity_fraction = ambiguity_count / window_length if window_length else 1.0
    coverage_rank = classify_coverage(primer_support, window_length, primer_set)
    tiebreak_length = (
        -window_length if primer_support == "none" else abs(window_length - primer_set.target_length)
    )

    metrics = SelectionMetrics(
        primer_support=primer_support,
        primer_mismatches=primer_mismatches,
        coverage_rank=coverage_rank,
        window_start=window_start,
        window_end=window_end,
        window_length=window_length,
        ambiguity_count=ambiguity_count,
        ambiguity_fraction=ambiguity_fraction,
        tiebreak_length=tiebreak_length,
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
    primer_set_name: str,
) -> None:
    """Write selected rows as TSV, with the sequence column replaced by the cropped window."""
    extra_fields = [
        "evospaice_primer_set",
        "evospaice_primer_support",
        "evospaice_primer_mismatches",
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
            out_row["evospaice_primer_set"] = primer_set_name
            out_row["evospaice_primer_support"] = cand.metrics.primer_support
            out_row["evospaice_primer_mismatches"] = str(cand.metrics.primer_mismatches)
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
    max_primer_mismatches: int,
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
    def pct(part: int, whole: int) -> str:
        return f"{100.0 * part / whole:.1f}%" if whole else "n/a"

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
    lines.append(f"Max mismatches:   {max_primer_mismatches} (per primer, 0 = exact match only)")
    if crop_window is not None:
        lines.append(f"Crop window:      {crop_window[0]}:{crop_window[1]}")
    lines.append("")

    lines.append("Row counts")
    lines.append("-" * 48)
    lines.append(f"Total rows read:                {total_rows}")
    lines.append(
        f"Rows after taxon/marker filter: {taxon_rows} ({pct(taxon_rows, total_rows)} of total)"
    )
    lines.append(f"Distinct BINs after filter:     {bins_seen}")
    lines.append(
        f"Selected BIN representatives:   {len(chosen)} ({pct(len(chosen), bins_seen)} of BINs)"
    )
    for reason, count in sorted(drop_counts.items()):
        lines.append(f"  dropped ({reason}): {count} ({pct(count, taxon_rows)} of filtered)")
    lines.append("")

    support_counts = Counter(cand.metrics.primer_support for cand in chosen)
    lines.append("Primer support among selected representatives")
    lines.append("-" * 48)
    for support in ("both", "forward_only", "reverse_only", "none"):
        count = support_counts.get(support, 0)
        lines.append(f"  {support}: {count} ({pct(count, len(chosen))})")
    lines.append("")

    matched = [cand for cand in chosen if cand.metrics.primer_support != "none"]
    if matched and max_primer_mismatches > 0:
        exact = sum(1 for cand in matched if cand.metrics.primer_mismatches == 0)
        fuzzy = len(matched) - exact
        lines.append("Exact vs. mismatch-tolerant matches (of matched representatives)")
        lines.append("-" * 48)
        lines.append(f"  exact (0 mismatches): {exact} ({pct(exact, len(matched))})")
        lines.append(f"  fuzzy (>0 mismatches): {fuzzy} ({pct(fuzzy, len(matched))})")
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
            lines.append(f"  {name}: {count} ({pct(count, taxon_rows)} of filtered)")
        lines.append("")

    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Input BCDM TSV file")
    parser.add_argument("--output", type=Path, required=True, help="Output path (.tsv or .fasta)")
    parser.add_argument("--taxon", default="phylum:Arthropoda")
    parser.add_argument("--marker-filter", default="COI-5P")
    parser.add_argument("--output-format", choices=["tsv", "fasta"], default="tsv")
    parser.add_argument("--primer-set", choices=list(PRIMER_SETS), default="leray")
    parser.add_argument("--forward-primer", default=None)
    parser.add_argument("--reverse-primer", default=None)
    parser.add_argument("--target-length", type=int, default=None)
    parser.add_argument("--min-length", type=int, default=None)
    parser.add_argument("--max-length", type=int, default=None)
    parser.add_argument(
        "--max-primer-mismatches",
        type=int,
        default=2,
        help=(
            "Max mismatches allowed per primer beyond an exact IUPAC match "
            "(seed-and-extend fallback). 0 = exact match only (old behaviour). "
            "Default 2 (~as forgiving as one SNP for a ~25bp primer)."
        ),
    )
    parser.add_argument("--crop-window", default="")
    parser.add_argument("--min-sequence-length", type=int, default=0)
    parser.add_argument("--max-ambiguity-fraction", type=float, default=1.0)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--report-top-n", type=int, default=15)
    parser.add_argument("--encoding", default="utf-8")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
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
    if args.max_primer_mismatches < 0:
        raise ValueError("--max-primer-mismatches must be >= 0")
    fwd_pattern, rev_pattern = compile_primer_patterns(primer_set, args.max_primer_mismatches)

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

        if args.min_sequence_length and len(cleaned_seq) < args.min_sequence_length:
            drop_counts["below_min_sequence_length"] += 1
            continue

        primer_window, metrics = assess_sequence(cleaned_seq, fwd_pattern, rev_pattern, primer_set)

        if metrics.ambiguity_fraction > args.max_ambiguity_fraction:
            drop_counts["too_ambiguous"] += 1
            continue

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
        write_tsv(args.output, chosen, fieldnames or [], columns["sequence"], primer_set.name)
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
        max_primer_mismatches=args.max_primer_mismatches,
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
