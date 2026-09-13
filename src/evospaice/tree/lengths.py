"""Branch-length strategies for fixed local topologies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import nnls

from .topology import LocalNode, TopologyResult


@dataclass(frozen=True)
class LengthResult:
    topology: TopologyResult
    method: str
    fit_error: float
    clamped_lengths: int


class BranchLengthSolver(Protocol):
    def solve(
        self,
        topology: TopologyResult,
        child_ids: list[str],
        distances: NDArray[np.float64],
    ) -> LengthResult: ...


class NonNegativeLeastSquaresSolver:
    """Fit non-negative edge lengths to observed child-to-child distances."""

    def __init__(self, fallback_length: float = 0.0) -> None:
        self._fallback_length = fallback_length

    def solve(
        self,
        topology: TopologyResult,
        child_ids: list[str],
        distances: NDArray[np.float64],
    ) -> LengthResult:
        edges: list[LocalNode] = []
        paths: dict[str, set[int]] = {}

        def collect(node: LocalNode, path: set[int]) -> None:
            if node.source_id is not None:
                paths[node.source_id] = path
                return
            for child in node.children:
                edge_index = len(edges)
                edges.append(child)
                collect(child, path | {edge_index})

        collect(topology.root, set())
        if len(child_ids) == 1:
            edges[0].length = self._fallback_length
            return LengthResult(topology, "fallback", 0.0, 0)
        if len(child_ids) == 2:
            half = max(0.0, float(distances[0, 1]) / 2.0)
            for edge in edges:
                edge.length = half
            return LengthResult(topology, "two_child_split", 0.0, 0)

        rows: list[list[float]] = []
        targets: list[float] = []
        for left_index, left in enumerate(child_ids):
            for right_index in range(left_index + 1, len(child_ids)):
                right = child_ids[right_index]
                route = paths[left] ^ paths[right]
                rows.append([1.0 if index in route else 0.0 for index in range(len(edges))])
                targets.append(float(distances[left_index, right_index]))

        design = np.asarray(rows, dtype=np.float64)
        observed = np.asarray(targets, dtype=np.float64)
        lengths, _ = nnls(design, observed)
        fitted = design @ lengths
        fit_error = float(np.sqrt(np.mean(np.square(fitted - observed))))
        for edge, length in zip(edges, lengths, strict=True):
            edge.length = float(length)
        return LengthResult(topology, "nnls", fit_error, 0)


def apply_fallback_lengths(topology: TopologyResult, length: float) -> LengthResult:
    def assign(node: LocalNode) -> None:
        for child in node.children:
            child.length = length
            assign(child)

    assign(topology.root)
    return LengthResult(topology, "policy_fallback", 0.0, 0)
