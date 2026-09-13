"""Application service coordinating one embedding-driven tree build."""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .backbone import TreeGraph, build_taxonomy_backbone, stable_node_id
from .distance import CosineDistanceProvider, DistanceProvider
from .inputs import load_inputs
from .lengths import (
    BranchLengthSolver,
    NonNegativeLeastSquaresSolver,
    apply_fallback_lengths,
)
from .models import BuildResult, InputPaths, NodeDiagnostic, TreeBuildConfig, TreeNode
from .output import ArtifactWriter
from .policy import TrustPolicy
from .representatives import CentroidMedoidSelector, RepresentativeSelector
from .topology import LocalNode, NeighborJoiningResolver, TopologyResolver, star_topology


class RepresentativeStore:
    """Write-once vector store that prevents representatives from drifting."""

    def __init__(self) -> None:
        self._values: dict[str, NDArray[np.float64]] = {}

    def freeze(self, node_id: str, vector: NDArray[np.floating]) -> None:
        if node_id in self._values:
            raise ValueError(f"representative already frozen: {node_id}")
        self._values[node_id] = np.asarray(vector, dtype=np.float64)

    def get_many(self, node_ids: list[str]) -> NDArray[np.float64]:
        return np.vstack([self._values[node_id] for node_id in node_ids])


class TreeBuilder:
    """Coordinates replaceable scientific strategies without owning file parsing."""

    def __init__(
        self,
        distance_provider: DistanceProvider,
        topology_resolver: TopologyResolver,
        branch_solver: BranchLengthSolver,
        representative_selector: RepresentativeSelector,
        artifact_writer: ArtifactWriter | None = None,
    ) -> None:
        self._distance_provider = distance_provider
        self._topology_resolver = topology_resolver
        self._branch_solver = branch_solver
        self._representative_selector = representative_selector
        self._artifact_writer = artifact_writer or ArtifactWriter()

    def build(self, paths: InputPaths, config: TreeBuildConfig) -> BuildResult:
        loaded = load_inputs(paths)
        policy = TrustPolicy.from_mapping(loaded.policy_data)
        graph = build_taxonomy_backbone(loaded.records)
        record_by_id = {record.record_id: record for record in loaded.records}
        representatives = RepresentativeStore()
        diagnostics: list[NodeDiagnostic] = []

        for node_id in graph.postorder():
            node = graph.nodes[node_id]
            if node.is_leaf:
                record = record_by_id[node.record_id or ""]
                representatives.freeze(node_id, loaded.vector_for(record))
                continue

            child_ids = list(node.child_ids)
            child_vectors = representatives.get_many(child_ids)
            local_distances = self._distance_provider.pairwise(child_vectors)
            topology, note = self._choose_topology(node, child_ids, local_distances, policy, config)
            if policy.should_scale(node):
                length_result = self._branch_solver.solve(topology, child_ids, local_distances)
            else:
                length_result = apply_fallback_lengths(topology, config.fallback_branch_length)
            self._graft(graph, node_id, length_result.topology.root)

            representative = self._representative_selector.select(child_vectors)
            representatives.freeze(node_id, representative.vector)
            diagnostics.append(
                NodeDiagnostic(
                    node_id=node_id,
                    rank=node.rank,
                    child_count=len(child_ids),
                    topology_method=topology.method,
                    length_method=length_result.method,
                    representative_method=representative.method,
                    fit_error=length_result.fit_error,
                    clamped_lengths=length_result.clamped_lengths,
                    distance_matrix_size=int(local_distances.size),
                    note=note,
                )
            )

        return self._artifact_writer.write(
            graph, loaded.records, diagnostics, paths, config, policy
        )

    def _choose_topology(
        self,
        node: TreeNode,
        child_ids: list[str],
        distances: NDArray[np.float64],
        policy: TrustPolicy,
        config: TreeBuildConfig,
    ):
        if len(child_ids) < 3:
            return star_topology(child_ids), ""
        if not policy.should_resolve(node):
            return star_topology(child_ids), "policy_preserved"
        if len(child_ids) > config.max_nj_children:
            return star_topology(child_ids), "fanout_limit"
        return self._topology_resolver.resolve(child_ids, distances), ""

    @staticmethod
    def _graft(graph: TreeGraph, parent_id: str, local_root: LocalNode) -> None:
        graph.nodes[parent_id].child_ids.clear()

        def attach(local: LocalNode, target_parent_id: str) -> None:
            length = max(0.0, float(local.length))
            if local.source_id is not None:
                child = graph.nodes[local.source_id]
                child.parent_id = target_parent_id
                child.branch_length = length
                graph.nodes[target_parent_id].child_ids.append(child.node_id)
                return

            synthetic_id = stable_node_id("nj", parent_id, *local.leaf_ids())
            synthetic = TreeNode(
                node_id=synthetic_id,
                label="",
                rank="synthetic",
                parent_id=target_parent_id,
                branch_length=length,
            )
            graph.add(synthetic)
            for child in local.children:
                attach(child, synthetic_id)

        for child in local_root.children:
            attach(child, parent_id)


def build_tree(paths: InputPaths, config: TreeBuildConfig | None = None) -> BuildResult:
    """Construct the default strategy graph and execute one complete build."""

    selected_config = config or TreeBuildConfig()
    builder = TreeBuilder(
        distance_provider=CosineDistanceProvider(),
        topology_resolver=NeighborJoiningResolver(),
        branch_solver=NonNegativeLeastSquaresSolver(selected_config.fallback_branch_length),
        representative_selector=CentroidMedoidSelector(selected_config.centroid_drift_limit),
    )
    return builder.build(paths, selected_config)
