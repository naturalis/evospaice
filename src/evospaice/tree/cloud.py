"""Azure Blob adapter for stateless Container Apps Job executions."""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .full_scale import QueueLease
from .models import BuildResult, InputPaths, TreeBuildConfig
from .pipeline import build_tree


class ObjectStore(Protocol):
    def download(self, object_name: str, destination: Path) -> None: ...

    def upload(self, source: Path, object_name: str) -> None: ...


class BlobObjectStore:
    """Authenticate with managed identity and transfer run artifacts."""

    def __init__(self, account_url: str, container: str) -> None:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.storage.blob import BlobServiceClient
        except ImportError as error:
            raise RuntimeError(
                "Azure execution requires the 'azure' optional dependency group"
            ) from error
        service = BlobServiceClient(account_url, credential=DefaultAzureCredential())
        self._container = service.get_container_client(container)

    def download(self, object_name: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as handle:
            self._container.download_blob(object_name).readinto(handle)

    def upload(self, source: Path, object_name: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        blob = self._container.get_blob_client(object_name)
        digest = _sha256(source)
        try:
            existing_digest = blob.get_blob_properties().metadata.get("sha256")
        except ResourceNotFoundError:
            pass
        else:
            if existing_digest == digest:
                return
            raise RuntimeError(f"refusing to overwrite different artifact: {object_name}")
        with source.open("rb") as handle:
            blob.upload_blob(handle, overwrite=False, metadata={"sha256": digest})


class AzureQueueWorkQueue:
    """Lease partition messages using managed identity and isolate exhausted work."""

    def __init__(
        self,
        account_url: str,
        queue_name: str,
        poison_queue_name: str,
        visibility_timeout: int = 21_600,
    ) -> None:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.storage.queue import QueueServiceClient
        except ImportError as error:
            raise RuntimeError(
                "Azure queue execution requires the 'azure' optional dependency group"
            ) from error
        service = QueueServiceClient(account_url, credential=DefaultAzureCredential())
        self._queue = service.get_queue_client(queue_name)
        self._poison_queue = service.get_queue_client(poison_queue_name)
        self._visibility_timeout = visibility_timeout

    def send(self, content: str) -> None:
        self._queue.send_message(content)

    def receive(self) -> QueueLease | None:
        messages = self._queue.receive_messages(
            messages_per_page=1,
            visibility_timeout=self._visibility_timeout,
        )
        message = next(iter(messages), None)
        if message is None:
            return None
        return QueueLease(
            content=str(message.content),
            message_id=str(message.id),
            pop_receipt=str(message.pop_receipt),
            dequeue_count=int(message.dequeue_count or 1),
        )

    def delete(self, lease: QueueLease) -> None:
        self._queue.delete_message(lease.message_id, lease.pop_receipt)

    def move_to_poison(self, lease: QueueLease, reason: str) -> None:
        payload = json.dumps(
            {
                "content": lease.content,
                "dequeue_count": lease.dequeue_count,
                "error": reason[:2048],
            },
            sort_keys=True,
        )
        self._poison_queue.send_message(payload)
        self.delete(lease)


@dataclass(frozen=True)
class CloudRunConfig:
    input_prefix: str
    output_prefix: str
    embeddings_name: str = "embeddings.npy"
    partition_root_rank: str | None = None


def run_cloud_tree(
    store: ObjectStore,
    cloud: CloudRunConfig,
    config: TreeBuildConfig | None = None,
) -> BuildResult:
    """Stage one immutable run locally, build it, and publish its artifacts."""

    with tempfile.TemporaryDirectory(prefix="evospaice-") as temporary_directory:
        work_dir = Path(temporary_directory)
        input_dir = work_dir / "input"
        output_dir = work_dir / "output"
        names = {
            "records": "records.tsv",
            "embeddings": cloud.embeddings_name,
            "embedding_index": "embedding-index.tsv",
            "trust_policy": "trust-policy.json",
        }
        local_paths = {key: input_dir / name for key, name in names.items()}
        for key, name in names.items():
            store.download(_join(cloud.input_prefix, name), local_paths[key])

        result = build_tree(
            InputPaths(
                records=local_paths["records"],
                embeddings=local_paths["embeddings"],
                embedding_index=local_paths["embedding_index"],
                trust_policy=local_paths["trust_policy"],
                output_dir=output_dir,
                partition_root_rank=cloud.partition_root_rank,
            ),
            config,
        )
        artifacts = [artifact for artifact in output_dir.rglob("*") if artifact.is_file()]
        artifacts.sort(key=_publication_order)
        for artifact in artifacts:
            relative_name = artifact.relative_to(output_dir).as_posix()
            store.upload(artifact, _join(cloud.output_prefix, relative_name))
        return result


def _join(prefix: str, name: str) -> str:
    return f"{prefix.strip('/')}/{name.lstrip('/')}"


def _publication_order(path: Path) -> tuple[int, str]:
    relative_name = path.as_posix()
    if relative_name.endswith("tree-manifest.json"):
        return 2, relative_name
    if relative_name.endswith("checkpoints/complete.json"):
        return 1, relative_name
    return 0, relative_name


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
