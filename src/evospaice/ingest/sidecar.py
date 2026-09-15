#!/usr/bin/env python3

"""Summarise a bcdm2tree sidecar TSV: what got lifted, and what it cost.

Answers three questions the run log cannot: how lopsided the lifted terminals
are, how many would stay put under a minority-support threshold, and which
internal taxa were dissolved because every terminal below them was lifted away.
Reads the file in one streaming pass, so an 88 MB sidecar costs nothing.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

THRESHOLDS: List[Tuple[str, float]] = [("1 record", 1), ("2 records", 2), ("5 records", 5)]
SHARES: List[float] = [0.01, 0.05, 0.10]


def parse_arguments() -> argparse.Namespace:
    """Define and parse the command line arguments, returning the namespace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", help="TSV written by bcdm2tree.py --sidecar")
    parser.add_argument("-n", "--top", type=int, default=15,
                        help="How many extreme cases to list (default: %(default)s).")
    return parser.parse_args()


def read_rows(location: str):
    """Yield sidecar rows with the pipe-delimited columns already split."""
    with open(location, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            row["lineages"] = row["lineages"].split("|")
            row["counts"] = [int(value) for value in row["counts"].split("|")]
            yield row


def summarise(location: str, top: int) -> None:
    """Print the placement, threshold and dissolution summaries for one sidecar."""
    placed_at: Counter = Counter()
    lift_rank: Counter = Counter()
    minority_records: Counter = Counter()
    minority_share: List[float] = []
    used_as_parent = set()
    seen_in_lineages: Dict[str, int] = defaultdict(int)
    extreme: List[Tuple[int, str, str]] = []
    terminals = lifted = suspect = 0

    for row in read_rows(location):
        terminals += 1
        placed_at[row["placed_at"].split(":")[0].split("__")[0]] += 1
        used_as_parent.add(row["placed_at"])
        for name in row["lineages"]:
            seen_in_lineages[name] += 1
        if row["suspect"] == "yes":
            suspect += 1
            extreme.append((len(row["lineages"]), row["terminal"], row["placed_at"]))
        if row["lifted"] != "yes":
            continue
        lifted += 1
        lift_rank[row["placed_at"].split(":")[0].split("__")[0]] += 1
        counts = sorted(row["counts"], reverse=True)
        minority = sum(counts[1:])
        minority_records[min(minority, 10)] += 1
        minority_share.append(minority / max(sum(counts), 1))

    print(f"{terminals} terminals, {lifted} lifted ({100.0 * lifted / max(terminals, 1):.1f}%), "
          f"{suspect} suspect")
    print("\nattachment rank:")
    for rank, count in placed_at.most_common():
        print(f"  {rank:12s} {count:>9d}")

    print("\nminority support of lifted terminals (records outside the largest lineage):")
    for size in sorted(minority_records):
        label = f"{size}" if size < 10 else "10+"
        print(f"  {label:>4s} record(s) {minority_records[size]:>9d}")
    for cutoff, _ in THRESHOLDS:
        limit = int(cutoff.split()[0])
        stay = sum(count for size, count in minority_records.items() if size <= limit)
        print(f"  would stay put if a minority of <= {cutoff:10s} did not trigger a lift: "
              f"{stay} ({100.0 * stay / max(lifted, 1):.1f}% of lifts)")
    for share in SHARES:
        stay = sum(1 for value in minority_share if value <= share)
        print(f"  would stay put if a minority below {share:.0%} of records did not trigger a lift: "
              f"{stay} ({100.0 * stay / max(lifted, 1):.1f}% of lifts)")

    dissolved = [name for name in seen_in_lineages if name not in used_as_parent]
    by_rank = Counter(name.split(":")[0].split("__")[0] for name in dissolved)
    print(f"\n{len(dissolved)} taxa appear in a tip's lineages but hold no terminal:")
    for rank, count in by_rank.most_common():
        print(f"  {rank:12s} {count:>9d}")

    if extreme:
        print(f"\nmost fragmented suspect terminals:")
        for lineages, terminal, target in sorted(extreme, reverse=True)[:top]:
            print(f"  {terminal:16s} {lineages:>3d} lineages -> {target}")


def main() -> int:
    """Run the summary over the sidecar named on the command line."""
    args = parse_arguments()
    try:
        summarise(args.sidecar, args.top)
    except (OSError, KeyError, ValueError) as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
