"""Taxonomy-backed tree graph construction and traversal."""

from __future__ import annotations

import hashlib

from .models import TreeNode, TreeRecord


def stable_node_id(kind: str, *parts: str) -> str:
    payload = "\x1f".join((kind, *parts)).encode("utf-8")
    return f"{kind}:{hashlib.sha256(payload).hexdigest()[:20]}"


class TreeGraph:
    """Owns tree mutation while keeping node relationships consistent."""

    def __init__(self, root: TreeNode) -> None:
        self.root_id = root.node_id
        self.nodes: dict[str, TreeNode] = {root.node_id: root}

    def add(self, node: TreeNode) -> None:
        if node.node_id in self.nodes:
            raise ValueError(f"duplicate tree node ID: {node.node_id}")
        self.nodes[node.node_id] = node
        if node.parent_id is not None:
            self.nodes[node.parent_id].child_ids.append(node.node_id)

    def postorder(self) -> list[str]:
        order: list[str] = []
        stack = [(self.root_id, False)]
        while stack:
            node_id, visited = stack.pop()
            if visited:
                order.append(node_id)
                continue
            stack.append((node_id, True))
            for child_id in reversed(self.nodes[node_id].child_ids):
                stack.append((child_id, False))
        return order


def build_taxonomy_backbone(records: tuple[TreeRecord, ...]) -> TreeGraph:
    """Build a path-keyed taxonomy tree and attach one leaf per record."""

    root = TreeNode(node_id="taxonomy:root", label="root", rank="root")
    graph = TreeGraph(root)
    path_to_id: dict[tuple[tuple[str, str], ...], str] = {}

    for record in sorted(records, key=lambda item: item.leaf_id):
        parent_id = graph.root_id
        path: list[tuple[str, str]] = []
        for rank, name in record.taxonomy:
            path.append((rank, name))
            path_key = tuple(path)
            node_id = path_to_id.get(path_key)
            if node_id is None:
                node_id = stable_node_id("taxonomy", *(f"{r}:{n}" for r, n in path_key))
                graph.add(TreeNode(node_id=node_id, label=name, rank=rank, parent_id=parent_id))
                path_to_id[path_key] = node_id
            parent_id = node_id

        graph.add(
            TreeNode(
                node_id=stable_node_id("leaf", record.leaf_id),
                label=record.leaf_id,
                rank="leaf",
                parent_id=parent_id,
                leaf_id=record.leaf_id,
                record_id=record.record_id,
                annotations={"bin_uri": record.bin_uri, "record_id": record.record_id},
            )
        )
    return graph
