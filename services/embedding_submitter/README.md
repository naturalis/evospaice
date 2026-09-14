# Omni-DNA embedding submitter

This Function receives `BlobCreated` events for FASTA files in the
`filtered-sequences` container and submits one Azure Machine Learning command
job to the scale-to-zero `gpu-NC24ADS-a100-dedicated` cluster. Job names and
output paths are deterministic from the source URL and ETag, so Event Grid
retries do not create duplicate runs. It reuses the workspace's proven cached
Omni20M environment and installs only its missing FAISS and `einops` packages at
job startup. AML downloads the source through the credentialless
`filteredsequences` datastore, and the worker streams that local file without
loading it into memory.

The AML worker streams the FASTA from Blob Storage, embeds records in batches
with `zehui127/Omni-DNA-20M` using the workspace's proven attended-token mean
pooling, and writes a versioned bundle to the `embedding-results` datastore:

```text
<source-name>/<source-etag>/
  index.faiss
  records.parquet
  manifest.json
```

`index.faiss` contains L2-normalized 256-dimensional vectors in an
`IndexIDMap2(IndexFlatIP)`. `records.parquet` maps each FAISS integer ID to the
source record number, full FASTA header and sequence, parsed taxonomy, and source
blob URL. `manifest.json` records the source ETag, model revision, pooling method,
counts, dimensions, and checksums.

## Deployment

```bash
./infra/deploy.sh hack --apply

export TF_DATA_DIR="$PWD/infra/.terraform/hack"
resource_group="$(terraform -chdir=infra output -raw resource_group_name)"
function_app="$(terraform -chdir=infra output -raw embedding_submitter_function_app_name)"
./services/embedding_submitter/deploy.sh "$resource_group" "$function_app"
```