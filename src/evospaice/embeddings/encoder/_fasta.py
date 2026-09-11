"""FASTA and TSV parsing utilities."""

from __future__ import annotations

import csv
from pathlib import Path


def parse_fasta(path: Path) -> tuple[list[str], list[str], dict[str, list[str]]]:
    """Return (ids, sequences, metadata) from a FASTA or TSV file.
    
    metadata is a dictionary mapping column names to lists of values,
    useful for storing taxonomy in TSV files.
    """
    ids: list[str] = []
    seqs: list[str] = []
    metadata: dict[str, list[str]] = {}
    
    if path.suffix.lower() in ('.tsv', '.csv', '.txt'):
        delimiter = ',' if path.suffix.lower() == '.csv' else '\t'
        with open(path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            if not reader.fieldnames:
                return ids, seqs
            headers = reader.fieldnames
            id_col = next((h for h in headers if h.lower() in ('processid', 'sequenceid', 'id')), headers[0])
            seq_col = next((h for h in headers if h.lower() in ('nucleotides', 'sequence', 'nuc')), None)
            
            if not seq_col:
                try:
                    row = next(reader)
                except StopIteration:
                    return ids, seqs
                for h, v in row.items():
                    if v and len(v) > 20 and all(c in 'ACGTN-' for c in v.upper()):
                        seq_col = h
                        break
                f.seek(0)
                next(reader)
            
            # Initialize metadata lists for all columns except the sequence column
            meta_cols = [h for h in headers if h != seq_col]
            for col in meta_cols:
                metadata[col] = []

            for row in reader:
                seq = row.get(seq_col, '')
                if seq:
                    ids.append(row.get(id_col, 'unknown_id'))
                    seqs.append(seq.replace('-', ''))
                    for col in meta_cols:
                        metadata[col].append(row.get(col, ''))
        return ids, seqs, metadata

    # Standard FASTA parsing
    current_seq_parts: list[str] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_seq_parts:
                    seqs.append("".join(current_seq_parts))
                    current_seq_parts = []
                ids.append(line[1:].split()[0])
            else:
                current_seq_parts.append(line)
        if current_seq_parts:
            seqs.append("".join(current_seq_parts))

    return ids, seqs, metadata
