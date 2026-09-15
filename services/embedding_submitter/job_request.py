"""Validated embedding-job request derived from an Event Grid BlobCreated event."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

_SAFE_NAME = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True)
class EmbeddingJobRequest:
    source_blob_url: str
    source_blob_name: str
    source_etag: str
    job_name: str
    output_prefix: str

    @classmethod
    def from_event(
        cls,
        payload: bytes,
        expected_host: str,
        expected_container: str,
    ) -> EmbeddingJobRequest:
        event = json.loads(payload)
        if not isinstance(event, dict):
            raise ValueError("Event Grid message must contain a JSON object")

        data = event.get("data")
        source_blob_url = data.get("url") if isinstance(data, dict) else None
        source_etag = data.get("eTag") if isinstance(data, dict) else None
        if not isinstance(source_blob_url, str) or not source_blob_url:
            raise ValueError("Event Grid message does not contain data.url")
        if not isinstance(source_etag, str) or not source_etag.strip('"'):
            raise ValueError("Event Grid message does not contain data.eTag")

        parsed = urlparse(source_blob_url)
        path_parts = unquote(parsed.path).strip("/").split("/", 1)
        if parsed.scheme != "https" or parsed.hostname != expected_host:
            raise ValueError("BlobCreated event came from an unexpected storage account")
        if len(path_parts) != 2 or path_parts[0] != expected_container:
            raise ValueError("BlobCreated event came from an unexpected container")
        if not path_parts[1].lower().endswith(('.fa', '.fasta', '.fna')):
            raise ValueError("Embedding input must be a FASTA blob")

        source_blob_name = path_parts[1]
        stem = PurePosixPath(source_blob_name).stem.lower()
        safe_stem = _SAFE_NAME.sub("-", stem).strip("-")[:32] or "fasta"
        etag = source_etag.strip('"').lower()
        fingerprint = hashlib.sha256(f"{source_blob_url}\n{etag}".encode()).hexdigest()[:12]
        return cls(
            source_blob_url=source_blob_url,
            source_blob_name=source_blob_name,
            source_etag=etag,
            job_name=f"embed-{safe_stem}-{fingerprint}",
            output_prefix=f"{safe_stem}/{etag}",
        )