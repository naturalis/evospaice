"""Validated species-split job request from an embedding index event."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class SpeciesSplitRequest:
    bundle_prefix: str
    job_prefix: str

    @classmethod
    def from_event(
        cls,
        payload: bytes,
        expected_host: str,
        expected_container: str,
    ) -> SpeciesSplitRequest:
        event = json.loads(payload)
        data = event.get("data") if isinstance(event, dict) else None
        blob_url = data.get("url") if isinstance(data, dict) else None
        etag = data.get("eTag") if isinstance(data, dict) else None
        if not isinstance(blob_url, str) or not blob_url:
            raise ValueError("Event Grid message does not contain data.url")
        if not isinstance(etag, str) or not etag.strip('"'):
            raise ValueError("Event Grid message does not contain data.eTag")

        parsed = urlparse(blob_url)
        path_parts = unquote(parsed.path).strip("/").split("/", 1)
        if parsed.scheme != "https" or parsed.hostname != expected_host:
            raise ValueError("Embedding event came from an unexpected storage account")
        if len(path_parts) != 2 or path_parts[0] != expected_container:
            raise ValueError("Embedding event came from an unexpected container")

        blob_name = PurePosixPath(path_parts[1])
        if blob_name.name != "index.faiss" or blob_name.parent == PurePosixPath("."):
            raise ValueError("Species splitting must be triggered by a bundle index.faiss")

        bundle_prefix = blob_name.parent.as_posix()
        fingerprint = hashlib.sha256(f"{blob_url}\n{etag.strip(chr(34))}".encode()).hexdigest()[:12]
        return cls(
            bundle_prefix=bundle_prefix,
            job_prefix=f"split-species-{fingerprint}",
        )