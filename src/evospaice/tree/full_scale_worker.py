"""Queue-driven worker for one immutable full-scale tree partition."""

from __future__ import annotations

from dataclasses import dataclass

from .cloud import CloudRunConfig, run_cloud_tree
from .full_scale import (
    ArtifactStore,
    PartitionWorkItem,
    WorkQueue,
    join_object,
    upload_json,
)
from .models import TreeBuildConfig


@dataclass(frozen=True)
class WorkerConfig:
    max_dequeue_count: int = 3

    def __post_init__(self) -> None:
        if self.max_dequeue_count < 1:
            raise ValueError("max dequeue count must be positive")


def run_partition_worker(
    store: ArtifactStore,
    queue: WorkQueue,
    worker_config: WorkerConfig | None = None,
    tree_config: TreeBuildConfig | None = None,
) -> str | None:
    selected_worker_config = worker_config or WorkerConfig()
    lease = queue.receive()
    if lease is None:
        return None

    try:
        item = PartitionWorkItem.from_json(lease.content)
        run_cloud_tree(
            store,
            CloudRunConfig(
                input_prefix=item.partition.input_prefix,
                output_prefix=item.partition.output_prefix,
                partition_root_rank=item.partition.taxonomy_path[-1][0],
            ),
            tree_config,
        )
        completion_object = join_object(
            item.run_prefix,
            f"work/completion/{item.partition.partition_id}.json",
        )
        upload_json(
            store,
            completion_object,
            {
                "schema_version": 1,
                "status": "complete",
                "partition_id": item.partition.partition_id,
                "leaf_count": item.partition.leaf_count,
                "tree_manifest": join_object(
                    item.partition.output_prefix,
                    "tree-manifest.json",
                ),
            },
        )
        queue.delete(lease)
        return item.partition.partition_id
    except Exception as error:
        if lease.dequeue_count >= selected_worker_config.max_dequeue_count:
            queue.move_to_poison(lease, f"{type(error).__name__}: {error}")
        raise