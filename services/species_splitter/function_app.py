"""Submit per-species FAISS splitting jobs to Azure Machine Learning."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import azure.functions as func
from azure.ai.ml import Input, MLClient, Output, command
from azure.ai.ml.entities import ManagedIdentityConfiguration
from azure.identity import DefaultAzureCredential

from job_request import SpeciesSplitRequest

app = func.FunctionApp()
logger = logging.getLogger("species_splitter")


def _submit_jobs(request: SpeciesSplitRequest) -> list[str]:
    client = MLClient(
        DefaultAzureCredential(),
        os.environ["AZURE_SUBSCRIPTION_ID"],
        os.environ["AZURE_RESOURCE_GROUP"],
        os.environ["AZUREML_WORKSPACE_NAME"],
    )
    worker_dir = Path(__file__).parent / "worker"
    input_path = (
        f"azureml://datastores/{os.environ['AZUREML_INPUT_DATASTORE']}/paths/"
        f"{request.bundle_prefix}"
    )
    shard_count = int(os.environ["SPECIES_SPLITTER_SHARD_COUNT"])
    submitted_jobs = []
    for shard_index in range(shard_count):
        output_path = (
            f"azureml://datastores/{os.environ['AZUREML_OUTPUT_DATASTORE']}/paths/"
            f"{request.bundle_prefix}"
        )
        job = command(
            name=f"{request.job_prefix}-s{shard_index:03d}",
            display_name=f"Split species shard {shard_index + 1}/{shard_count}",
            experiment_name="species-faiss-splitting",
            tags={
                "pipeline": "species-splitter",
                "bundle_prefix": request.bundle_prefix,
                "shard_index": str(shard_index),
                "shard_count": str(shard_count),
            },
            code=worker_dir,
            command=(
                "pip install --disable-pip-version-check -r runtime-requirements.txt && "
                "python split_bundle.py "
                '"--input-dir=${{inputs.bundle}}" '
                '"--output-dir=${{outputs.species_bundles}}" '
                '"--shard-index=${{inputs.shard_index}}" '
                '"--shard-count=${{inputs.shard_count}}"'
            ),
            inputs={
                "bundle": Input(type="uri_folder", mode="download", path=input_path),
                "shard_index": shard_index,
                "shard_count": shard_count,
            },
            outputs={
                "species_bundles": Output(type="uri_folder", mode="rw_mount", path=output_path),
            },
            environment=os.environ["AZUREML_ENVIRONMENT"],
            compute=os.environ["AZUREML_COMPUTE_NAME"],
            identity=ManagedIdentityConfiguration(
                client_id=os.environ["AZUREML_IDENTITY_CLIENT_ID"],
            ),
        )
        submitted_jobs.append(client.jobs.create_or_update(job).name)
    return submitted_jobs


@app.function_name("submit_species_split_job")
@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name="species-split-trigger-events",
    connection="ServiceBusConnection",
)
def submit_species_split_job(message: func.ServiceBusMessage) -> None:
    request = SpeciesSplitRequest.from_event(
        message.get_body(),
        expected_host=os.environ["EMBEDDING_BLOB_HOST"],
        expected_container=os.environ["EMBEDDING_CONTAINER"],
    )
    logger.info("Submitting %s for %s", request.job_prefix, request.bundle_prefix)
    job_names = _submit_jobs(request)
    logger.info("Submitted Azure ML jobs: %s", ", ".join(job_names))