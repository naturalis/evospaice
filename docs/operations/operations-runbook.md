# Operations runbook

## Prerequisites

- Azure CLI authenticated with `az login`.
- Terraform available on `PATH`.
- Access to the hack subscription, Terraform backend, AML workspace, and storage.

Verify the active account:

```bash
az account show --query '{subscription:id,user:user.name}' --output json
```

## Deploy infrastructure

Plan first:

```bash
./infra/deploy.sh hack
```

Review the plan for replacements or deletes, then apply:

```bash
./infra/deploy.sh hack --apply
```

## Deploy Functions

```bash
export TF_DATA_DIR="$PWD/infra/.terraform/hack"
resource_group="$(terraform -chdir=infra output -raw resource_group_name)"

class_filter="$(terraform -chdir=infra output -raw class_filter_function_app_name)"
embed_submitter="$(terraform -chdir=infra output -raw embedding_submitter_function_app_name)"
species_splitter="$(terraform -chdir=infra output -raw species_splitter_function_app_name)"

./services/class_filter/deploy.sh "$resource_group" "$class_filter"
./services/embedding_submitter/deploy.sh "$resource_group" "$embed_submitter"
./services/species_splitter/deploy.sh "$resource_group" "$species_splitter"
```

Function runtime storage uses managed identity. If a new Flex app reports
`Unable to access AzureWebJobsStorage`, verify that `AzureWebJobsStorage` is empty,
`AzureWebJobsStorage__accountName` is set, and the Function identity has Blob
Owner, Queue Contributor, and Table Contributor on its runtime storage account.

## Start a pipeline

Upload a trigger JSON file to `pipeline-triggers`:

```json
{
  "source_blob_url": "https://<account>.blob.core.windows.net/<container>/<file>.fasta",
  "target_class": "Insecta"
}
```

The remaining stages start from BlobCreated events automatically.

## Check queues

```bash
az servicebus queue show \
  --resource-group <resource-group> \
  --namespace-name <service-bus-namespace> \
  --name <queue-name> \
  --query '{active:countDetails.activeMessageCount,deadLetter:countDetails.deadLetterMessageCount}'
```

Queues:

- `fasta-filter-trigger-events`
- `fasta-embedding-trigger-events`
- `species-split-trigger-events`

## Check AML jobs

Use Azure ML Studio, or query ARM:

```bash
az rest --method get --url \
  'https://management.azure.com/<workspace-resource-id>/jobs?api-version=2024-04-01'
```

Experiments:

- `omni-dna-embeddings`
- `species-faiss-splitting`

Species jobs are tagged with `bundle_prefix`, `shard_index`, and `shard_count`.
Worker logs contain machine-readable `PHASE`, `PROGRESS`, and `SUMMARY` JSON.

## Cancel a job

```bash
az rest --method post --url \
  'https://management.azure.com/<workspace-resource-id>/jobs/<job-name>/cancel?api-version=2024-04-01'
```

After cancellation, remove only that job's incomplete output prefix. Do not delete
a previous completed version.

## Retry safely

Job names are deterministic for a source URL and ETag. To retry corrected code,
write a new source ETag. For large blobs, use asynchronous server-side copy and
verify `properties.copy.status == success` before deleting the staging blob.

Use short-lived, read-only user-delegation SAS tokens only for manual copy
operations. Never store SAS values in source control or logs.

## Dead-letter recovery

1. Inspect Function exceptions and Application Insights traces.
2. Correct and deploy the root cause.
3. Confirm Function host storage and RBAC are healthy.
4. Resubmit the original event or source blob.
5. Purge or replay dead-letter messages only after preserving diagnostic details.

## Final validation

- Every queue has zero active and dead-letter messages.
- Every AML shard reports `Completed` with no errors.
- Manifest record totals reconcile to the source.
- Each species has one `.faiss`, `.parquet`, and `.json` file.
- `unknown.faiss`, `unknown.parquet`, and `unknown.json` exist when unknown rows occur.
- Terraform reports: `No changes. Your infrastructure matches the configuration.`
