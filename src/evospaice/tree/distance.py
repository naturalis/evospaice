"""Distance strategies that only accept the current node's vectors."""

from __future__ import annotations

from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class DistanceProvider(Protocol):
    name: str

    def pairwise(self, vectors: NDArray[np.floating]) -> NDArray[np.float64]: ...


class CosineDistanceProvider:
    """Calculate a finite square cosine-distance block on demand."""

    name = "cosine"

    def pairwise(self, vectors: NDArray[np.floating]) -> NDArray[np.float64]:
        matrix = np.asarray(vectors, dtype=np.float64)
        if matrix.ndim != 2:
            raise ValueError("vectors must be a two-dimensional matrix")
        norms = np.linalg.norm(matrix, axis=1)
        if np.any(norms == 0) or not np.isfinite(matrix).all():
            raise ValueError("vectors must be finite and non-zero")
        normalized = matrix / norms[:, None]
        distances = np.clip(1.0 - normalized @ normalized.T, 0.0, 2.0)
        distances = (distances + distances.T) / 2.0
        np.fill_diagonal(distances, 0.0)
        return distances
