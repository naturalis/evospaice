# Azure Batch architecture for building the tree

> **Alternative design:** The project has selected Azure Container Apps Jobs
> as the execution platform. See the
> [Container Apps Jobs tree architecture](azure-container-apps-tree-architecture.md).
> This document remains as the direct Azure Batch alternative.

## 1. Recommendation

Use these Azure services for the tree-building pipeline:

| Azure service | Use in Evospaice | Required? |
| --- | --- | --- |
| **Azure Data Lake Storage Gen2** | Store metadata, embeddings, policies, checkpoints, trees, diagnostics, and manifests | Yes |
| **Azure Container Registry** | Store the versioned Evospaice container image | Yes |
| **Azure Batch** | Run the finite CPU jobs that validate data, build the backbone, resolve subtrees, calculate branch lengths, and assemble the final tree | Yes |
| **Managed Identities for Azure resources** | Let Batch read storage and pull container images without saved passwords or access keys | Yes |
| **Azure Monitor and Log Analytics** | Collect platform logs, job status, failures, duration, and resource measurements | Yes for shared runs |
| **Azure Key Vault** | Store any external secret that cannot use managed identity | Only when a secret exists |
| **Azure Data Factory** | Trigger and monitor the Batch workflow as part of a wider data pipeline | Optional later |

This pipeline does **not** need AKS, Azure Functions, Cosmos DB, Azure SQL, or a
web application. It is a file-based batch computation, so those services would
add operational work without solving a current requirement.

Because the embeddings already exist, the tree-building deployment also does
not need Azure Machine Learning or GPU compute. Add an Azure Machine Learning
batch endpoint or a GPU-enabled Batch pool only if embedding generation becomes
part of the deployed workflow.

## 2. Why Azure Batch is the default compute service

The tree build is a finite job with a mix of sequential and parallel work:

- input checks and backbone creation are mostly single jobs;
- independent taxonomy subtrees can be processed in parallel;
- parent nodes wait for their child subtrees; and
- final assembly is a reduce step.

Azure Batch is designed for large parallel and high-performance batch jobs. It
creates VM pools, schedules tasks, supports container workloads, and can scale
the pool with demand. There is no separate Batch service charge; cost comes
from the VMs, storage, and networking used by the workload.

For a small hackathon subset, Azure Container Apps Jobs is a valid simpler
alternative because it runs finite containers and scales to zero. Move to
Azure Batch when the job needs memory-optimized VM sizes, many parallel subtree
tasks, Spot capacity, or more control over local disks and task scheduling.

## 3. Azure data flow

```text
Developer or GitHub Actions
  |
  +--> build container ----------------------> Azure Container Registry
  |
  +--> upload run inputs --------------------> ADLS Gen2
  |
  +--> submit Batch job
             |
             v
       Azure Batch pool
         1. validate IDs, vectors, and policy
         2. build or load taxonomy backbone
         3. divide work into independent taxonomic subtrees
         4. resolve and scale subtrees in parallel
         5. combine subtree results and process parent nodes
         6. validate and publish the final tree
             |
             +--> checkpoints and outputs ---> ADLS Gen2
             +--> status and metrics --------> Azure Monitor / Log Analytics
```

The container image is the same in development, CI, Container Apps Jobs, and
Batch. Only the command and configuration change between stages.

## 4. Storage design

Create one StorageV2 account with hierarchical namespace enabled, making it
ADLS Gen2. Keep files in run-specific directories:

```text
evospaice/
  reference/
    bold/<release-id>/records.tsv
    bold/<release-id>/source-manifest.json
    models/<embedding-version>/
  runs/<run-id>/
    input/
      records.tsv
      embeddings.npy
      embedding-index.tsv
      trust-policy.json
    work/
      partitions/
      checkpoints/
      subtree-results/
    output/
      scaled-tree.nwk
      node-diagnostics.tsv
      excluded-records.tsv
      tree-manifest.json
    logs/
```

Recommended controls:

- Keep active inputs, checkpoints, and current outputs in the Hot tier.
- Use lifecycle rules to move old successful runs to Cool storage and delete
  abandoned temporary data after an agreed retention period.
- Enable blob and container soft delete for important manifests and final
  outputs. Blob versioning is not supported when hierarchical namespace is
  enabled.
- Treat a run directory as immutable after `tree-manifest.json` is written.
- Store checksums in the manifest and verify them before every stage.
- Use separate `input`, `work`, and `output` paths so partial results cannot be
  mistaken for a finished run.

NumPy cannot safely memory-map a remote blob as if it were a local file. A
Batch task should download its required embedding shard to the node's temporary
SSD, memory-map it there, upload its result, and then discard the local copy.
For the subset MVP, downloading the complete embedding file to one node is
acceptable. At larger scale, partition vectors by independent taxonomy subtree
so workers do not all download the full matrix.

## 5. Batch job design

### 5.1 MVP: one pool, one tree-building task

Start with one Linux Batch pool using a memory-optimized VM size. Configure the
pool to scale from zero to one node. One container task runs the complete
post-embedding pipeline:

```text
validate -> build backbone -> post-order resolve and scale -> verify -> publish
```

This is the best first deployment because it matches the local implementation,
has few moving parts, and proves actual memory and runtime needs. Select the VM
size only after measuring the subset locally. Check regional quota and SKU
availability before fixing a size in infrastructure code.

### 5.2 Scale-out: subtree map and parent reduce

When one node is no longer enough, use a Batch job with dependent tasks:

| Task | Runs on | Reads | Writes |
| --- | --- | --- | --- |
| `prepare` | Dedicated memory-optimized node | Metadata, embedding index, policy | Validated join, backbone, subtree partition plan |
| `subtree-*` | Parallel nodes; Spot allowed | One subtree plus its vector shard | Resolved subtree, representative vector, diagnostics, checkpoint |
| `reduce` | Dedicated memory-optimized node | All completed subtree outputs | Combined tree and parent-level results |
| `verify` | Dedicated or general-purpose node | Combined tree, input manifest | Validation summary and candidate outputs |
| `publish` | Small general-purpose node | Verified candidate outputs | Immutable final outputs and manifest |

Choose partition boundaries, such as order or family, so each subtree is
independent below the boundary. The `reduce` task waits for all required
subtree tasks, loads only their root representatives, and continues the
post-order algorithm toward the global root.

Use Spot nodes only for idempotent `subtree-*` tasks that have checkpoints and
can tolerate eviction. Use dedicated nodes for `prepare`, `reduce`, and
`publish`, where interruption delays the whole run. Set maximum node counts so
an accidental job cannot scale without a cost limit.

### 5.3 Batch pool choices

- Use a current Linux image supported by the project dependencies.
- Begin with a memory-optimized VM family because the backbone and local
  distance blocks are more likely to be memory-bound than CPU-bound.
- Use local temporary SSD for downloaded vector shards and temporary matrices.
- Set the pool minimum to zero when idle.
- Keep the pool in the same Azure region as storage to reduce transfer time and
  cost.
- Use a container start task only for shared node preparation. Keep application
  dependencies inside the versioned container image.
- Measure first; do not assume that more nodes help the sequential parent
  reduction step.

## 6. Container image and deployment

Build one Linux image containing:

- the packaged `evospaice` code;
- pinned Python dependencies;
- the CLI entry point;
- no datasets, model weights, credentials, or environment-specific settings.

Tag images with an immutable commit SHA. A friendly tag such as `candidate`
may point to that image, but Batch run manifests must store the immutable image
digest.

Use Azure Container Registry for the image. Give the Batch pool identity only
the permission needed to pull images. A CI workflow may build and push the
image using workload identity federation instead of a long-lived client secret.

## 7. Identity and security

Use a user-assigned managed identity for Batch compute. Give it the smallest
roles needed:

- `Storage Blob Data Reader` plus appropriate ADLS ACLs for immutable reference
  and input paths;
- `Storage Blob Data Contributor` plus appropriate ADLS ACLs only where the
  job must write `work`, `output`, and `logs`; and
- `AcrPull` on the container registry.

Do not put storage keys, SAS tokens, or registry passwords in command lines,
container environment files, source control, or manifests. Use Key Vault only
for a third-party secret that cannot be replaced with managed identity.

For an internal or regulated deployment, disable public storage access and add
private endpoints for both the Blob and DFS endpoints of the ADLS Gen2 account,
plus private access to ACR as required. For a time-limited hackathon using
public BOLD data, start with Entra-authenticated access and restricted network
rules, then add private networking when organisational policy requires it.

## 8. Monitoring and recovery

Send Batch account diagnostics to Log Analytics and use Azure Monitor alerts
for failed tasks, unavailable nodes, long queue times, and jobs that exceed the
expected duration.

The application should also write structured JSON logs to standard output and
upload these run measures:

- records and vectors accepted or rejected;
- nodes completed and remaining;
- largest child count and local distance matrix;
- elapsed time and peak memory by stage;
- NJ, NNLS, medoid, and branch-clamp fallback counts;
- checkpoint path; and
- final tree and manifest checksums.

Batch retries should be limited. Retry transient storage or node failures, but
do not repeatedly retry deterministic data or algorithm errors. Because every
subtree result is written under a stable ID and checksum, a replacement task
can reuse completed work after a node failure or Spot eviction.

## 9. Cost controls

- Scale Batch pools to zero when no job is running.
- Set a hard maximum node count per pool.
- Use Spot nodes only for retryable subtree tasks.
- Delete local disks and Batch pools after the run; durable outputs belong in
  ADLS Gen2.
- Apply storage lifecycle rules to checkpoints, logs, and old runs.
- Keep compute and storage in the same region.
- Tag resources and run manifests with project, environment, owner, and run ID.
- Create an Azure budget and alerts before a full-scale test.
- Benchmark one, then several, then many subtrees before requesting large
  quotas.

## 10. MVP and full-scale service sets

### Hackathon MVP

Provision only:

1. one ADLS Gen2 storage account;
2. one Azure Container Registry;
3. one Azure Batch account and one autoscaling CPU pool;
4. one user-assigned managed identity; and
5. one Log Analytics workspace with Azure Monitor diagnostics.

Run the complete subset tree as one container task. This is enough to validate
the design and measure the real bottleneck.

### Full-scale candidate

Keep the MVP services, then add:

- separate dedicated and Spot Batch pools;
- subtree partitioning and dependent Batch tasks;
- private endpoints and tighter storage ACLs;
- automated lifecycle and budget policies; and
- optionally, Data Factory when this pipeline must be scheduled with external
  ingestion or downstream systems.

Do not add AKS unless the team later needs Kubernetes APIs, custom schedulers,
or a shared Kubernetes platform. Do not add Azure Machine Learning to the tree
stage unless model execution, model registry, or ML experiment tracking becomes
a requirement.

## 11. Service choices by workstream

| Workstream | Azure services |
| --- | --- |
| WS0 - Foundation | ACR, managed identity, Log Analytics, and infrastructure as code |
| WS1 - Ingest and backbone | ADLS Gen2 and a CPU Batch task |
| WS2 - Precomputed vectors | ADLS Gen2 only for the tree scope; optional GPU Batch or Azure Machine Learning batch endpoint if embeddings must be regenerated |
| WS3 - Tree building | Azure Batch, ADLS Gen2, ACR, and Azure Monitor |
| WS4 - Validation | CPU Batch tasks reading candidate trees and reference data from ADLS Gen2 |
| WS5 - Integration and scale | Batch job/task dependencies, Monitor, budgets, and optional Data Factory |
| WS6 - Visualisation | Local tools or a small Container Apps Job; publish only approved static artifacts |
| WS7 - Diversity and curation | Optional CPU Batch or Container Apps Job |
| WS8 - Demo and decision | ADLS Gen2 output package; existing collaboration tools rather than a new Azure application |

## 12. Official guidance

- [Azure Batch overview](https://learn.microsoft.com/azure/batch/batch-technical-overview)
- [Run container workloads on Azure Batch](https://learn.microsoft.com/azure/batch/batch-docker-container-workloads)
- [Configure managed identities in Batch pools](https://learn.microsoft.com/azure/batch/managed-identity-pools)
- [Use a managed identity with Azure Container Registry](https://learn.microsoft.com/azure/container-registry/container-registry-authentication-managed-identity)
- [Azure Container Apps Jobs](https://learn.microsoft.com/azure/container-apps/jobs)
- [Azure Container Apps serverless GPUs](https://learn.microsoft.com/azure/container-apps/gpu-serverless-overview)
- [Azure Machine Learning batch endpoints](https://learn.microsoft.com/azure/machine-learning/concept-endpoints-batch)
- [Azure Data Lake Storage introduction](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-introduction)
- [Soft delete for blobs](https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-overview)
- [Blob Storage lifecycle management](https://learn.microsoft.com/azure/storage/blobs/lifecycle-management-overview)
- [Background-job architecture guidance](https://learn.microsoft.com/azure/architecture/best-practices/background-jobs)
