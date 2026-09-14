# Species FAISS splitter

This Function receives `BlobCreated` events for `index.faiss` files in the
`embedding-results` container and submits eight Azure Machine Learning command
jobs to the scale-to-zero `cpu-species-split-dedicated` cluster. A stable species
hash assigns each species to exactly one shard.

The worker joins global FAISS IDs to `records.parquet`, partitions records by the
`species` column, reconstructs each subset from the global index, and writes one
three-file set per species to the version-matched path in `species-results`:

```text
<source>/<etag>/
  danaus-plexippus-b0b40e6e0c.faiss
  danaus-plexippus-b0b40e6e0c.parquet
  danaus-plexippus-b0b40e6e0c.json
  unknown.faiss
  unknown.parquet
  unknown.json
```

The hash suffix prevents sanitized species names from colliding. Null, blank,
`None`, `unknown`, `unidentified`, and `unclassified` labels are grouped into the
three `unknown` files in its assigned shard. FAISS IDs remain the original global
IDs, allowing every subset vector to map directly back to its FASTA record.
Temporary partitions stay on node-local storage. Each shard writes completed
files through a shared read-write Blob mount into the same version folder.
Hash-suffixed species keys are globally unique, so concurrent shards cannot
overwrite each other's files.

Each worker emits structured `PROGRESS` JSON every 250,000 metadata records and
every 250 completed species. Events include shard index/count, completed/total,
percentage, elapsed time, throughput, ETA, selected records, and records written.
AML jobs are tagged with the bundle prefix and shard identity so progress can be
aggregated across all shards.

## Deployment

```bash
./infra/deploy.sh hack --apply

export TF_DATA_DIR="$PWD/infra/.terraform/hack"
resource_group="$(terraform -chdir=infra output -raw resource_group_name)"
function_app="$(terraform -chdir=infra output -raw species_splitter_function_app_name)"
./services/species_splitter/deploy.sh "$resource_group" "$function_app"
```