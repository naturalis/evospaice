"""Extract process-ID-to-species metadata from a unified taxonomy Newick tree."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, TextIO


@dataclass(slots=True)
class Node:
    """Minimal Newick node required for taxonomy extraction."""

    label: str = ""
    quoted: bool = False
    children: list[Node] = field(default_factory=list)


class NewickParser:
    """Parse labels and topology while ignoring branch lengths and comments."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.position = 0

    def parse(self) -> Node:
        root = self._parse_subtree()
        self._skip_ignored()
        if self._peek() != ";":
            raise ValueError(f"expected ';' at character {self.position}")
        self.position += 1
        self._skip_ignored()
        if self.position != len(self.text):
            raise ValueError(f"unexpected content at character {self.position}")
        return root

    def _parse_subtree(self) -> Node:
        self._skip_ignored()
        if self._peek() == "(":
            self.position += 1
            children = [self._parse_subtree()]
            while True:
                self._skip_ignored()
                if self._peek() == ",":
                    self.position += 1
                    children.append(self._parse_subtree())
                elif self._peek() == ")":
                    self.position += 1
                    break
                else:
                    raise ValueError(f"expected ',' or ')' at character {self.position}")
            label, quoted = self._parse_label()
            node = Node(label=label, quoted=quoted, children=children)
        else:
            label, quoted = self._parse_label()
            if not label:
                raise ValueError(f"expected tip label at character {self.position}")
            node = Node(label=label, quoted=quoted)

        self._skip_ignored()
        if self._peek() == ":":
            self.position += 1
            start = self.position
            while self._peek() and self._peek() not in ",();[":
                self.position += 1
            float(self.text[start : self.position].strip())
        self._skip_ignored()
        return node

    def _parse_label(self) -> tuple[str, bool]:
        self._skip_ignored()
        if self._peek() != "'":
            start = self.position
            while self._peek() and self._peek() not in ":,();[":
                self.position += 1
            return self.text[start : self.position].strip(), False

        self.position += 1
        value: list[str] = []
        while self.position < len(self.text):
            character = self._peek()
            self.position += 1
            if character != "'":
                value.append(character)
            elif self._peek() == "'":
                value.append("'")
                self.position += 1
            else:
                return "".join(value), True
        raise ValueError("unterminated quoted label")

    def _skip_ignored(self) -> None:
        while True:
            while self._peek().isspace():
                self.position += 1
            if self._peek() != "[":
                return
            depth = 0
            while self.position < len(self.text):
                character = self._peek()
                self.position += 1
                if character == "[":
                    depth += 1
                elif character == "]":
                    depth -= 1
                    if depth == 0:
                        break
            else:
                raise ValueError("unterminated Newick comment")

    def _peek(self) -> str:
        return self.text[self.position] if self.position < len(self.text) else ""


def iter_species_metadata(root: Node) -> Iterator[tuple[str, str]]:
    """Yield each terminal label and its nearest quoted ancestor."""
    stack: list[tuple[Node, str | None]] = [(root, None)]
    while stack:
        node, species = stack.pop()
        if node.quoted:
            species = node.label
        if not node.children:
            if species is not None:
                yield node.label, species.replace("_", " ")
            continue
        stack.extend((child, species) for child in reversed(node.children))


def write_species_metadata(source: Path, output: TextIO) -> int:
    """Parse ``source`` and write Taxonium-compatible TSV metadata."""
    root = NewickParser(source.read_text(encoding="utf-8")).parse()
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(("node", "species"))
    count = 0
    for process_id, species in iter_species_metadata(root):
        writer.writerow((process_id, species))
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Unified taxonomy Newick tree")
    parser.add_argument("output", type=Path, help="Output TSV metadata file")
    args = parser.parse_args()

    with args.output.open("w", encoding="utf-8", newline="") as output:
        count = write_species_metadata(args.source, output)
    print(f"wrote {count} process-to-species mappings to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())