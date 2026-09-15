"""SequenceEncoder protocol — the contract every model adapter must satisfy."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class SequenceEncoder(Protocol):
    """Encode DNA sequences into fixed-size embedding vectors."""

    @property
    def embedding_dim(self) -> int:
        """Dimensionality of the output embeddings."""
        ...

    def encode(self, sequences: list[str], batch_size: int = 64) -> np.ndarray:
        """Return an (N, D) float32 embedding matrix for *sequences*."""
        ...
