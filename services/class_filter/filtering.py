"""Streaming FASTA filtering helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator

_CLASS_FIELD = re.compile(
    r"(?:^|[\s|;])(?:class\s*[=:]\s*|c__)([^\s|;]+)",
    re.IGNORECASE,
)
_OUTPUT_CHUNK_SIZE = 4 * 1024 * 1024


class FastaFormatError(ValueError):
    """Raised when sequence data appears before the first FASTA header."""


@dataclass
class FilterStats:
    records_seen: int = 0
    records_written: int = 0


def _iter_lines(chunks: Iterable[bytes]) -> Iterator[bytes]:
    pending = b""
    for chunk in chunks:
        if not chunk:
            continue
        lines = (pending + chunk).split(b"\n")
        pending = lines.pop()
        for line in lines:
            yield line + b"\n"
    if pending:
        yield pending


def _header_class(header: bytes) -> str | None:
    try:
        text = header.decode("utf-8")
    except UnicodeDecodeError as error:
        raise FastaFormatError("FASTA headers must be UTF-8 encoded") from error

    match = _CLASS_FIELD.search(text)
    return match.group(1) if match else None


def filter_fasta_by_class(
    chunks: Iterable[bytes],
    target_class: str,
    stats: FilterStats | None = None,
) -> Iterator[bytes]:
    """Yield records whose header contains ``class=<target_class>``.

    Header fields may be separated by whitespace, ``|``, or ``;`` and may use
    either ``=`` or ``:`` between key and value. Input is consumed incrementally
    so memory use is bounded by the largest downloaded chunk.
    """
    stats = stats or FilterStats()
    include_record = False
    seen_header = False
    output_buffer = bytearray()

    for line in _iter_lines(chunks):
        if line.startswith(b">"):
            seen_header = True
            stats.records_seen += 1
            record_class = _header_class(line[1:].rstrip(b"\r\n"))
            include_record = (
                record_class is not None
                and record_class.casefold() == target_class.casefold()
            )
            if include_record:
                stats.records_written += 1
        elif not seen_header and line.strip():
            raise FastaFormatError("Sequence data found before the first FASTA header")

        if include_record:
            output_buffer.extend(line)
            if len(output_buffer) >= _OUTPUT_CHUNK_SIZE:
                yield bytes(output_buffer)
                output_buffer.clear()

    if output_buffer:
        yield bytes(output_buffer)