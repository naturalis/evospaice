from __future__ import annotations

from pathlib import Path

from evospaice.tree.cloud import CloudRunConfig, run_cloud_tree

REPOSITORY_ROOT = Path(__file__).parents[1]
MOCK_DATA = REPOSITORY_ROOT / "data" / "mock-tree"


class MemoryObjectStore:
    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.objects = {
            f"runs/mock/input/{name}": (MOCK_DATA / name).read_bytes()
            for name in (
                "records.tsv",
                "embeddings.tsv",
                "embedding-index.tsv",
                "trust-policy.json",
            )
        }

    def download(self, object_name: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.objects[object_name])

    def upload(self, source: Path, object_name: str) -> None:
        content = source.read_bytes()
        existing = self.objects.get(object_name)
        if existing is not None and existing != content:
            raise RuntimeError(f"immutable object differs: {object_name}")
        self.objects[object_name] = content
        self.uploads.append(object_name)


def test_cloud_adapter_stages_and_publishes_an_idempotent_run() -> None:
    store = MemoryObjectStore()
    run = CloudRunConfig(
        input_prefix="runs/mock/input",
        output_prefix="runs/mock/output",
        embeddings_name="embeddings.tsv",
    )

    first = run_cloud_tree(store, run)
    second = run_cloud_tree(store, run)

    assert first.leaf_count == second.leaf_count == 100
    assert "runs/mock/output/scaled-tree.nwk" in store.objects
    assert "runs/mock/output/tree-manifest.json" in store.objects
    assert "runs/mock/output/checkpoints/complete.json" in store.objects
    assert store.uploads[-1] == "runs/mock/output/tree-manifest.json"