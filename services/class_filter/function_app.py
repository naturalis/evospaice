"""Azure Function entry point for filtering a FASTA blob by taxonomic class."""

from __future__ import annotations

import json
import logging
import os
from urllib.parse import urlparse

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobClient, ContainerClient

from filtering import FilterStats, filter_fasta_by_class
from trigger import TriggerRequest

app = func.FunctionApp()
logger = logging.getLogger("class_filter")


def _allowed_source_hosts() -> set[str]:
    return {
        host.strip().lower()
        for host in os.environ["ALLOWED_SOURCE_BLOB_HOSTS"].split(",")
        if host.strip()
    }


def _validate_source_url(source_blob_url: str) -> None:
    parsed = urlparse(source_blob_url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("source_blob_url must be a complete HTTPS Azure Blob URL")
    if parsed.hostname.lower() not in _allowed_source_hosts():
        raise ValueError(f"Source storage account is not allowed: {parsed.hostname}")


def _download_trigger(blob_url: str, credential: DefaultAzureCredential) -> TriggerRequest:
    trigger_blob = BlobClient.from_blob_url(blob_url, credential=credential)
    return TriggerRequest.from_json(trigger_blob.download_blob().readall())


def _filter_source(request: TriggerRequest, credential: DefaultAzureCredential) -> FilterStats:
    _validate_source_url(request.source_blob_url)
    source_blob = BlobClient.from_blob_url(request.source_blob_url, credential=credential)
    output_container = ContainerClient(
        account_url=os.environ["OUTPUT_STORAGE_ACCOUNT_URL"],
        container_name=os.environ["OUTPUT_CONTAINER_NAME"],
        credential=credential,
    )
    output_blob = output_container.get_blob_client(request.output_blob_name)
    stats = FilterStats()

    output_blob.upload_blob(
        filter_fasta_by_class(
            source_blob.download_blob().chunks(),
            target_class=request.target_class,
            stats=stats,
        ),
        overwrite=True,
    )
    return stats


@app.function_name("filter_fasta_by_class")
@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name="fasta-filter-trigger-events",
    connection="ServiceBusConnection",
)
def filter_fasta(message: func.ServiceBusMessage) -> None:
    """Process an Event Grid BlobCreated event delivered through Service Bus."""
    event = json.loads(message.get_body().decode("utf-8"))
    trigger_blob_url = event.get("data", {}).get("url")
    if not isinstance(trigger_blob_url, str) or not trigger_blob_url:
        raise ValueError("Event Grid message does not contain data.url")

    credential = DefaultAzureCredential()
    request = _download_trigger(trigger_blob_url, credential)
    logger.info(
        "Filtering FASTA source %s for class %s",
        request.source_blob_url,
        request.target_class,
    )
    stats = _filter_source(request, credential)
    logger.info(
        "Wrote %d of %d FASTA records to %s/%s",
        stats.records_written,
        stats.records_seen,
        os.environ["OUTPUT_CONTAINER_NAME"],
        request.output_blob_name,
    )