"""Domain models for the embedding-driven tree builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TAXONOMY_RANKS = (
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "subfamily",
    "tribe",
    "genus",
    "species",
    "subspecies",
)


@dataclass(frozen=True)
class TreeRecord:
    """One selected tree tip and its source-record provenance."""

    leaf_id: str
    record_id: str
    bin_uri: str
    taxonomy: tuple[tuple[str, str], ...]
    embedding_row: int


@dataclass
class TreeNode:
    """A compact mutable node; vectors are held in a separate store."""

    node_id: str
    label: str
    rank: str
    parent_id: str | None = None
    child_ids: list[str] = field(default_factory=list)
    leaf_id: str | None = None
    record_id: str | None = None
    branch_length: float | None = None
    annotations: dict[str, str] = field(default_factory=dict)

    @property
    def is_leaf(self) -> bool:
        return self.leaf_id is not None


@dataclass(frozen=True)
class TreeBuildConfig:
    """Algorithm settings that must be recorded for reproducibility."""

    metric: str = "cosine"
    representative: str = "centroid-medoid"
    max_nj_children: int = 256
    centroid_drift_limit: float = 0.35
    fallback_branch_length: float = 0.0
    random_seed: int = 42

    def __post_init__(self) -> None:
        if self.max_nj_children < 3:
            raise ValueError("max_nj_children must be at least 3")
        if not 0.0 <= self.centroid_drift_limit <= 2.0:
            raise ValueError("centroid_drift_limit must be between 0 and 2")
        if self.fallback_branch_length < 0.0:
            raise ValueError("fallback_branch_length cannot be negative")


@dataclass(frozen=True)
class InputPaths:
    records: Path
    embeddings: Path
    output_dir: Path
    embedding_index: Path | None = None
    trust_policy: Path | None = None
    partition_root_rank: str | None = None

    def __post_init__(self) -> None:
        if (
            self.partition_root_rank is not None
            and self.partition_root_rank not in TAXONOMY_RANKS
        ):
            raise ValueError(f"unsupported partition root rank: {self.partition_root_rank}")


@dataclass(frozen=True)
class NodeDiagnostic:
    node_id: str
    rank: str
    child_count: int
    topology_method: str
    length_method: str
    representative_method: str
    fit_error: float
    clamped_lengths: int
    distance_matrix_size: int
    note: str = ""


@dataclass(frozen=True)
class BuildResult:
    tree_path: Path
    diagnostics_path: Path
    exclusions_path: Path
    manifest_path: Path
    leaf_count: int
    node_count: int


JsonObject = dict[str, Any]