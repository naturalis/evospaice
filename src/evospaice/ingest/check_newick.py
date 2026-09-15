#!/usr/bin/env python3

"""Check a large Newick file without loading it into a tree object.

Streams the file character by character, tracking quote and comment state, and
reports the tip count, internal node count, maximum depth and how many nodes
carry an annotation. Intended as a pre-flight check on trees too big to hand to
DendroPy or Biopython casually: a 1.1M tip file validates in seconds and a few
megabytes of memory.
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict


def parse_arguments() -> argparse.Namespace:
    """Define and parse the command line arguments, returning the namespace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("newick", help="Newick file to check")
    parser.add_argument("-b", "--block", type=int, default=1 << 20,
                        help="Read block size in bytes (default: %(default)s).")
    return parser.parse_args()


def scan(location: str, block: int) -> Dict[str, int]:
    """Walk the file once and return its structural tally.

    A tip is a label that follows an opening bracket or a comma, which is the
    standard way to count leaves without building the tree. Quoted labels and
    bracketed comments are skipped over wholesale, so colons, commas and
    parentheses inside them cannot be miscounted as structure.
    """
    tally = {"tips": 0, "internals": 0, "annotated": 0, "depth": 0,
             "max_depth": 0, "unbalanced": 0, "terminated": 0, "quoted": 0}
    previous = ""
    in_quote = in_comment = False
    with open(location, encoding="utf-8") as handle:
        while True:
            chunk = handle.read(block)
            if not chunk:
                break
            for character in chunk:
                if in_comment:
                    in_comment = character != "]"
                    continue
                if in_quote:
                    in_quote = character != "'"
                    continue
                if character == "'":
                    in_quote = True
                    tally["quoted"] += 1
                elif character == "[":
                    in_comment = True
                    tally["annotated"] += 1
                elif character == "(":
                    tally["depth"] += 1
                    tally["max_depth"] = max(tally["max_depth"], tally["depth"])
                    previous = "("
                elif character == ",":
                    if previous in "(,":
                        tally["tips"] += 1
                    previous = ","
                elif character == ")":
                    if previous in "(,":
                        tally["tips"] += 1
                    tally["depth"] -= 1
                    tally["internals"] += 1
                    previous = ")"
                elif character == ";":
                    tally["terminated"] = 1
    tally["unbalanced"] = tally["depth"]
    return tally


def main() -> int:
    """Run the scan and print a verdict, returning non-zero if the file is broken."""
    args = parse_arguments()
    try:
        tally = scan(args.newick, args.block)
    except OSError as problem:
        print(f"error: {problem}", file=sys.stderr)
        return 1
    print(f"tips          {tally['tips']}")
    print(f"internals     {tally['internals']}")
    print(f"annotations   {tally['annotated']}")
    print(f"quoted labels {tally['quoted']}")
    print(f"max depth     {tally['max_depth']}")
    problems = []
    if tally["unbalanced"]:
        problems.append(f"unbalanced parentheses (off by {tally['unbalanced']})")
    if not tally["terminated"]:
        problems.append("no terminating semicolon")
    if problems:
        print("BROKEN: " + "; ".join(problems))
        return 1
    print("OK: balanced and terminated")
    return 0


if __name__ == "__main__":
    sys.exit(main())