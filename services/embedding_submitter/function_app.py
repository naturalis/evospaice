"""Submit Omni-DNA embedding jobs to Azure Machine Learning."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import azure.functions as func
from azure.ai.ml import Input, MLClient, Output, command
from azure.ai.ml.entities import ManagedIdentityConfiguration
from azure.identity import DefaultAzureCredential

from job_request import EmbeddingJobRequest

app = func.FunctionApp()
logger = logging.getLogger("embedding_submitter")


def _submit_job(request: EmbeddingJobRequest) -> str:
    credential = DefaultAzureCredential()
    client = MLClient(
        credential,
        os.environ["AZURE_SUBSCRIPTION_ID"],
        os.environ["AZURE_RESOURCE_GROUP"],
        os.environ["AZUREML_WORKSPACE_NAME"],
    )
    worker_dir = Path(__file__).parent / "worker"
    input_path = (
        f"azureml://datastores/{os.environ['AZUREML_INPUT_DATASTORE']}/paths/"
        f"{request.source_blob_name}"
    )
    output_path = (
        f"azureml://datastores/{os.environ['AZUREML_OUTPUT_DATASTORE']}/paths/"
        f"{request.output_prefix}"
    )
    job = command(
        name=request.job_name,
        display_name=f"Omni-DNA embeddings: {request.source_blob_name}",
        experiment_name="omni-dna-embeddings",
        code=worker_dir,
        command=(
            "pip install --disable-pip-version-check -r runtime-requirements.txt && "
            "python embed_fasta.py "
            '"--source-fasta=${{inputs.source_fasta}}" '
            '"--source-blob-url=${{inputs.source_blob_url}}" '
            '"--source-etag=${{inputs.source_etag}}" '
            '"--output-dir=${{outputs.bundle}}" '
            '"--model-id=${{inputs.model_id}}" '
            '"--batch-size=${{inputs.batch_size}}" '
            '"--max-length=${{inputs.max_length}}"'
        ),
        inputs={
            "source_fasta": Input(type="uri_file", mode="download", path=input_path),
            "source_blob_url": request.source_blob_url,
            "source_etag": request.source_etag,
            "model_id": os.environ["OMNI_DNA_MODEL_ID"],
            "batch_size": int(os.environ["OMNI_DNA_BATCH_SIZE"]),
            "max_length": int(os.environ["OMNI_DNA_MAX_LENGTH"]),
        },
        outputs={
            "bundle": Output(type="uri_folder", mode="rw_mount", path=output_path),
        },
        environment=os.environ["AZUREML_ENVIRONMENT"],
        compute=os.environ["AZUREML_COMPUTE_NAME"],
        identity=ManagedIdentityConfiguration(
            client_id=os.environ["AZUREML_IDENTITY_CLIENT_ID"],
        ),
    )
    submitted = client.jobs.create_or_update(job)
    return submitted.name


@app.function_name("submit_omni_dna_embedding_job")
@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name="fasta-embedding-trigger-events",
    connection="ServiceBusConnection",
)
def submit_embedding_job(message: func.ServiceBusMessage) -> None:
    request = EmbeddingJobRequest.from_event(
        message.get_body(),
        expected_host=os.environ["FILTERED_FASTA_BLOB_HOST"],
        expected_container=os.environ["FILTERED_FASTA_CONTAINER"],
    )
    logger.info("Submitting %s for %s", request.job_name, request.source_blob_url)
    job_name = _submit_job(request)
    logger.info("Submitted Azure ML job %s", job_name)