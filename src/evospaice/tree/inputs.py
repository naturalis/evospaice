"""Validated file adapters for tree-building inputs."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from .models import InputPaths, TAXONOMY_RANKS, TreeRecord


class InputValidationError(ValueError):
    """Raised when input files violate the tree-building contract."""


@dataclass(frozen=True)
class LoadedInputs:
    records: tuple[TreeRecord, ...]
    embeddings: NDArray[np.floating]
    policy_data: dict[str, object]

    def vector_for(self, record: TreeRecord) -> NDArray[np.floating]:
        return self.embeddings[record.embedding_row]


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None:
            raise InputValidationError(f"{path} has no header")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def _load_embeddings(path: Path) -> NDArray[np.floating]:
    if path.suffix.lower() == ".npy":
        embeddings = np.load(path, mmap_mode="r", allow_pickle=False)
    else:
        embeddings = np.loadtxt(path, delimiter="\t", dtype=np.float32, ndmin=2)
    if embeddings.ndim != 2:
        raise InputValidationError("embeddings must be a two-dimensional array")
    if embeddings.shape[0] == 0 or embeddings.shape[1] == 0:
        raise InputValidationError("embeddings cannot be empty")
    if not np.isfinite(embeddings).all():
        raise InputValidationError("embeddings contain non-finite values")
    if np.any(np.linalg.norm(embeddings, axis=1) == 0):
        raise InputValidationError("embeddings contain a zero-length vector")
    return embeddings


def _load_index(path: Path | None, record_rows: list[dict[str, str]]) -> dict[str, int]:
    if path is None:
        return {row["record_id"]: index for index, row in enumerate(record_rows)}

    rows = _read_tsv(path)
    required = {"record_id", "row_index"}
    if not rows or not required.issubset(rows[0]):
        raise InputValidationError("embedding index requires record_id and row_index columns")

    index: dict[str, int] = {}
    used_rows: set[int] = set()
    for row in rows:
        record_id = row["record_id"]
        if not record_id or record_id in index:
            raise InputValidationError(f"duplicate or empty record_id in embedding index: {record_id!r}")
        try:
            row_index = int(row["row_index"])
        except ValueError as error:
            raise InputValidationError(f"invalid row_index for {record_id!r}") from error
        if row_index in used_rows:
            raise InputValidationError(f"duplicate embedding row_index: {row_index}")
        index[record_id] = row_index
        used_rows.add(row_index)
    return index


def load_inputs(paths: InputPaths) -> LoadedInputs:
    """Load and validate records, embeddings, index, and optional policy."""

    record_rows = _read_tsv(paths.records)
    required = {"leaf_id", "record_id", "bin_uri"}
    if not record_rows or not required.issubset(record_rows[0]):
        raise InputValidationError("records require leaf_id, record_id, and bin_uri columns")

    embeddings = _load_embeddings(paths.embeddings)
    embedding_index = _load_index(paths.embedding_index, record_rows)
    record_ids: set[str] = set()
    leaf_ids: set[str] = set()
    records: list[TreeRecord] = []

    for row in record_rows:
        leaf_id = row["leaf_id"]
        record_id = row["record_id"]
        if not leaf_id or not record_id:
            raise InputValidationError("leaf_id and record_id cannot be empty")
        if leaf_id in leaf_ids:
            raise InputValidationError(f"duplicate leaf_id: {leaf_id}")
        if record_id in record_ids:
            raise InputValidationError(f"duplicate record_id: {record_id}")
        if record_id not in embedding_index:
            raise InputValidationError(f"record has no embedding index entry: {record_id}")

        taxonomy = tuple(
            (rank, " ".join(row.get(rank, "").split()))
            for rank in TAXONOMY_RANKS
            if row.get(rank, "").strip()
        )
        if not taxonomy:
            raise InputValidationError(f"record has no taxonomy: {record_id}")
        leaf_ids.add(leaf_id)
        record_ids.add(record_id)
        records.append(
            TreeRecord(
                leaf_id=leaf_id,
                record_id=record_id,
                bin_uri=row["bin_uri"],
                taxonomy=taxonomy,
                embedding_row=embedding_index[record_id],
            )
        )

    if set(embedding_index) != record_ids:
        extras = sorted(set(embedding_index) - record_ids)
        raise InputValidationError(f"embedding index contains records absent from metadata: {extras[:5]}")
    expected_rows = set(range(embeddings.shape[0]))
    actual_rows = set(embedding_index.values())
    if actual_rows != expected_rows:
        raise InputValidationError("embedding row indexes must cover every vector exactly once")

    for record in records:
        if not 0 <= record.embedding_row < embeddings.shape[0]:
            raise InputValidationError(f"embedding row is out of range: {record.record_id}")

    policy_data: dict[str, object] = {}
    if paths.trust_policy is not None:
        with paths.trust_policy.open(encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise InputValidationError("trust policy must be a JSON object")
        policy_data = value

    return LoadedInputs(tuple(records), embeddings, policy_data)
