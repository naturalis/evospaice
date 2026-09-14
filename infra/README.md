# Container Apps Jobs MVP

> This directory's root template is the small four-file MVP. For the
> 6.98-million-record FAISS/Parquet workflow and the isolated
> `rg-evoispace-tree-lp` deployment, use the [full-scale infrastructure](full-scale/README.md).

The template provisions the manually triggered tree-building path described in
the [Container Apps Jobs architecture](../docs/azure-container-apps-tree-architecture.md):

- one Azure Container Registry with local administrator access disabled;
- one ADLS Gen2 storage account and private blob container;
- one user-assigned managed identity;
- `AcrPull` on the registry and `Storage Blob Data Contributor` on storage;
- one Consumption Container Apps environment connected to Log Analytics; and
- one manual Container Apps Job with one replica, bounded retries, and no secrets.

## Deployment contract

1. Build [the repository Dockerfile](../Dockerfile) and publish it to the
   generated registry as `evospaice/tree-builder:<immutable-tag>`.
2. Put these four objects below the configured `inputPrefix` in the generated
   blob container: `records.tsv`, `embeddings.npy`, `embedding-index.tsv`, and
   `trust-policy.json`.
3. Replace the values in [main.bicepparam](main.bicepparam), deploy
   [main.bicep](main.bicep) at resource-group scope, and start the manual job.
4. Treat `tree-manifest.json` below `outputPrefix` as the publication marker.

The application downloads one run to container-local temporary storage,
executes the same tree builder used by the local CLI, validates the result, and
uploads data artifacts first, `checkpoints/complete.json` next, and
`tree-manifest.json` last. Existing objects with matching SHA-256 metadata are
accepted during a retry; a different object at the same output path fails the
run rather than overwriting published data.

Choose a new output prefix for changed inputs or settings. The default
Consumption request is 2 vCPU and 4 GiB. Increase it only within the Consumption
limit, or move the job to a measured Dedicated workload profile.