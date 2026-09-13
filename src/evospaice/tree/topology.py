"""Local topology strategies for direct children of one taxonomy node."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


@dataclass
class LocalNode:
    source_id: str | None = None
    children: list[LocalNode] = field(default_factory=list)
    length: float = 0.0

    def leaf_ids(self) -> tuple[str, ...]:
        if self.source_id is not None:
            return (self.source_id,)
        return tuple(sorted(leaf for child in self.children for leaf in child.leaf_ids()))


@dataclass(frozen=True)
class TopologyResult:
    root: LocalNode
    method: str


class TopologyResolver(Protocol):
    def resolve(
        self, child_ids: list[str], distances: NDArray[np.float64]
    ) -> TopologyResult: ...


def star_topology(child_ids: list[str], method: str = "preserved") -> TopologyResult:
    children = [LocalNode(source_id=value) for value in child_ids]
    return TopologyResult(LocalNode(children=children), method)


class NeighborJoiningResolver:
    """Deterministic Neighbor-Joining for a bounded local distance block."""

    def resolve(
        self, child_ids: list[str], distances: NDArray[np.float64]
    ) -> TopologyResult:
        if len(child_ids) < 3:
            return star_topology(child_ids)
        if distances.shape != (len(child_ids), len(child_ids)):
            raise ValueError("distance matrix shape does not match child IDs")

        active = list(child_ids)
        nodes = {child_id: LocalNode(source_id=child_id) for child_id in child_ids}
        values = {
            tuple(sorted((left, right))): float(distances[i, j])
            for i, left in enumerate(child_ids)
            for j, right in enumerate(child_ids)
            if i < j
        }
        merge_index = 0

        def get_distance(left: str, right: str) -> float:
            return values[tuple(sorted((left, right)))]

        while len(active) > 2:
            count = len(active)
            totals = {
                item: sum(get_distance(item, other) for other in active if other != item)
                for item in active
            }
            candidates = []
            for left_index, left in enumerate(active):
                for right in active[left_index + 1 :]:
                    score = (count - 2) * get_distance(left, right) - totals[left] - totals[right]
                    candidates.append((score, min(left, right), max(left, right)))
            _, left, right = min(candidates)
            distance = get_distance(left, right)
            delta = (totals[left] - totals[right]) / (count - 2)
            nodes[left].length = (distance + delta) / 2.0
            nodes[right].length = distance - nodes[left].length

            merged_id = f"@nj-{merge_index}"
            merge_index += 1
            nodes[merged_id] = LocalNode(children=[nodes[left], nodes[right]])
            remaining = [item for item in active if item not in {left, right}]
            for other in remaining:
                values[tuple(sorted((merged_id, other)))] = (
                    get_distance(left, other) + get_distance(right, other) - distance
                ) / 2.0
            active = [*remaining, merged_id]

        left, right = active
        final_distance = get_distance(left, right)
        nodes[left].length = final_distance / 2.0
        nodes[right].length = final_distance / 2.0
        return TopologyResult(LocalNode(children=[nodes[left], nodes[right]]), "neighbor_joining")
