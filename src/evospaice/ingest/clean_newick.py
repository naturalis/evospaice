#!/usr/bin/env python3
"""Normalize a taxonomy Newick tree for Taxonium.

The input may contain quoted or unquoted labels, taxonomy labels on internal
nodes, existing branch lengths, and bracketed NHX annotations. The output
keeps NHX annotations, preserves taxonomy labels as Taxonium-safe internal
labels, collapses single-child nodes, normalizes labels, and writes
``default_length`` on every remaining node. Existing branch lengths are
replaced by that fixed value.

Command-line usage::

    python clean_newick.py input.tre output.tre --length 1.0
"""

import argparse
import re
from pathlib import Path


def clean_newick(newick_str: str, default_length: float = 1.0) -> str:
    """Return a Taxonium-compatible Newick tree with labels and annotations.

    NHX comments are copied verbatim. Taxonomy labels attached to internal
    nodes are normalized and retained as internal labels. Unary nodes are
    collapsed; their labels are added to the surviving child's NHX metadata.
    """
    position = 0

    def skip_space() -> None:
        nonlocal position
        while position < len(newick_str) and newick_str[position].isspace():
            position += 1

    def read_label() -> str:
        nonlocal position
        skip_space()
        if position < len(newick_str) and newick_str[position] == "'":
            position += 1
            start = position
            while position < len(newick_str) and newick_str[position] != "'":
                position += 1
            label = newick_str[start:position]
            if position < len(newick_str):
                position += 1
            return label

        start = position
        while position < len(newick_str) and newick_str[position] not in ",();:":
            position += 1
        return newick_str[start:position].strip()

    def skip_branch_length() -> None:
        nonlocal position
        skip_space()
        if position < len(newick_str) and newick_str[position] == ":":
            position += 1
            while position < len(newick_str) and newick_str[position] not in ",();":
                position += 1

    def read_annotations() -> str:
        nonlocal position
        annotations = []
        skip_space()
        while position < len(newick_str) and newick_str[position] == "[":
            start = position
            depth = 0
            while position < len(newick_str):
                if newick_str[position] == "[":
                    depth += 1
                elif newick_str[position] == "]":
                    depth -= 1
                position += 1
                if depth == 0:
                    break
            if depth != 0:
                raise ValueError("Unbalanced Newick annotation")
            annotations.append(newick_str[start:position])
            skip_space()
        return "".join(annotations)

    def parse_node():
        nonlocal position
        skip_space()
        if position >= len(newick_str):
            raise ValueError("Unexpected end of Newick tree")

        if newick_str[position] == "(":
            position += 1
            children = [parse_node()]
            while True:
                skip_space()
                if position >= len(newick_str) or newick_str[position] != ",":
                    break
                position += 1
                children.append(parse_node())
            skip_space()
            if position >= len(newick_str) or newick_str[position] != ")":
                raise ValueError("Unbalanced Newick parentheses")
            position += 1
            label = read_label()
            annotation = read_annotations()
            skip_branch_length()
            return {"children": children, "label": label, "annotation": annotation}

        label = read_label()
        if not label:
            raise ValueError(f"Empty leaf label at character {position}")
        annotation = read_annotations()
        skip_branch_length()
        return {"children": None, "label": label, "annotation": annotation}

    tree = parse_node()
    skip_space()
    if position < len(newick_str) and newick_str[position] == ";":
        position += 1
    skip_space()
    if position != len(newick_str):
        raise ValueError(f"Unexpected data at character {position}")

    def normalize(node):
        if node["children"] is None:
            node["label"] = re.sub(
                r"[^A-Za-z0-9_.-]+", "_", node["label"]
            ).strip("_") or "unknown"
            return node
        node["label"] = re.sub(
            r"[^A-Za-z0-9_.-]+", "_", node["label"]
        ).strip("_")
        node["children"] = [normalize(child) for child in node["children"]]
        if len(node["children"]) == 1:
            child = node["children"][0]
            if node["label"]:
                child["annotation"] = (
                    f"[&taxon={node['label']}]"
                    + child["annotation"]
                )
            child["annotation"] = node["annotation"] + child["annotation"]
            return child
        return node

    def serialize(node) -> str:
        annotation = node["annotation"]
        if node["children"] is None:
            return f"{node['label']}{annotation}:{default_length}"
        children = ",".join(serialize(child) for child in node["children"])
        label = node["label"]
        return f"({children}){label}{annotation}:{default_length}"

    return serialize(normalize(tree)) + ";\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input Newick tree, including optional NHX annotations")
    parser.add_argument("output", type=Path, help="Output normalized Newick tree")
    parser.add_argument(
        "--length", type=float, default=1.0,
        help="Branch length written on every output node (default: %(default)s)",
    )
    args = parser.parse_args()

    source = args.input.read_text(encoding="utf-8")
    result = clean_newick(source, args.length)
    args.output.write_text(result, encoding="utf-8")
    print(f"Input: {len(source):,} bytes")
    print(f"Output: {len(result):,} bytes")
    print(f"Output file: {args.output}")


if __name__ == "__main__":
    main()
