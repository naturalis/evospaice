"""Streaming FASTA parsing and BOLD taxonomy extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator

_BOLD_TAXONOMY = re.compile(r"(?:^|;)([a-z]+)__([^;]*)", re.IGNORECASE)
_RANK_COLUMNS = {
    "k": "kingdom",
    "p": "phylum",
    "c": "class",
    "o": "order",
    "f": "family",
    "g": "genus",
    "s": "species",
}


@dataclass(frozen=True)
class FastaRecord:
    ordinal: int
    record_id: str
    header: str
    sequence: str
    taxonomy: dict[str, str | None]


def _iter_lines(chunks: Iterable[bytes]) -> Iterator[bytes]:
    pending = b""
    for chunk in chunks:
        if not chunk:
            continue
        lines = (pending + chunk).split(b"\n")
        pending = lines.pop()
        for line in lines:
            yield line.rstrip(b"\r")
    if pending:
        yield pending.rstrip(b"\r")


def _metadata(header: str) -> tuple[str, dict[str, str | None]]:
    identifier = header.split(maxsplit=1)[0]
    if identifier.startswith("BOLD|"):
        parts = identifier.split("|")
        record_id = parts[1] if len(parts) > 1 and parts[1] else identifier
    else:
        record_id = identifier

    ranks: dict[str, str | None] = {column: None for column in _RANK_COLUMNS.values()}
    for rank, value in _BOLD_TAXONOMY.findall(header):
        column = _RANK_COLUMNS.get(rank.lower())
        if column and value and value.casefold() != "none":
            ranks[column] = value
    return record_id, ranks


def iter_fasta_records(chunks: Iterable[bytes]) -> Iterator[FastaRecord]:
    header: str | None = None
    sequence_parts: list[str] = []
    ordinal = 0

    for raw_line in _iter_lines(chunks):
        if raw_line.startswith(b">"):
            if header is not None:
                record_id, taxonomy = _metadata(header)
                yield FastaRecord(
                    ordinal=ordinal,
                    record_id=record_id,
                    header=header,
                    sequence="".join(sequence_parts),
                    taxonomy=taxonomy,
                )
                ordinal += 1
            header = raw_line[1:].decode("utf-8")
            sequence_parts = []
        elif raw_line.strip():
            if header is None:
                raise ValueError("Sequence data found before the first FASTA header")
            sequence_parts.append(raw_line.decode("ascii").strip().upper())

    if header is not None:
        record_id, taxonomy = _metadata(header)
        yield FastaRecord(
            ordinal=ordinal,
            record_id=record_id,
            header=header,
            sequence="".join(sequence_parts),
            taxonomy=taxonomy,
        )