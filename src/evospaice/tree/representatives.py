"""Strategies for reducing child vectors to one parent representative."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class RepresentativeResult:
    vector: NDArray[np.float64]
    method: str
    centroid_drift: float


class RepresentativeSelector(Protocol):
    def select(self, vectors: NDArray[np.floating]) -> RepresentativeResult: ...


class CentroidMedoidSelector:
    """Use an equal-child centroid, falling back to its nearest child."""

    def __init__(self, drift_limit: float) -> None:
        self._drift_limit = drift_limit

    def select(self, vectors: NDArray[np.floating]) -> RepresentativeResult:
        matrix = np.asarray(vectors, dtype=np.float64)
        centroid = matrix.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm == 0:
            normalized_children = matrix / np.linalg.norm(matrix, axis=1)[:, None]
            vector = normalized_children[0]
            return RepresentativeResult(vector, "medoid", 1.0)

        centroid = centroid / norm
        normalized_children = matrix / np.linalg.norm(matrix, axis=1)[:, None]
        child_distances = np.clip(1.0 - normalized_children @ centroid, 0.0, 2.0)
        nearest_index = int(np.argmin(child_distances))
        drift = float(child_distances[nearest_index])
        if drift > self._drift_limit:
            return RepresentativeResult(normalized_children[nearest_index], "medoid", drift)
        return RepresentativeResult(centroid, "centroid", drift)
