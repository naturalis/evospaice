"""Trust-policy decisions for topology and branch scaling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .models import TreeNode


def _rank_set(value: object, default: Iterable[str]) -> frozenset[str]:
    if value is None:
        return frozenset(default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("policy rank lists must contain strings")
    return frozenset(value)


@dataclass(frozen=True)
class TrustPolicy:
    version: str
    resolve_ranks: frozenset[str]
    scale_ranks: frozenset[str]

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "TrustPolicy":
        return cls(
            version=str(data.get("version", "candidate-v1")),
            resolve_ranks=_rank_set(data.get("resolve_ranks"), ("genus", "species")),
            scale_ranks=_rank_set(data.get("scale_ranks"), ("*",)),
        )

    @staticmethod
    def _allows(ranks: frozenset[str], node: TreeNode) -> bool:
        return "*" in ranks or node.rank in ranks

    def should_resolve(self, node: TreeNode) -> bool:
        return self._allows(self.resolve_ranks, node)

    def should_scale(self, node: TreeNode) -> bool:
        return self._allows(self.scale_ranks, node)
