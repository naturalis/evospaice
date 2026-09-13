# Azure Container Apps Jobs architecture for building the tree

## 1. Recommendation

Use **Azure Container Apps Jobs** as the execution platform for the
tree-building pipeline.

| Azure service | Use in Evospaice | Required? |
| --- | --- | --- |
| **Azure Container Apps environment** | Provides the managed execution, network, and logging boundary | Yes |
| **Azure Container Apps Jobs** | Run validation, backbone construction, subtree processing, reduction, verification, and publication | Yes |
| **Azure Data Lake Storage Gen2** | Stores metadata, embeddings, policies, checkpoints, trees, diagnostics, manifests, and queue messages | Yes |
| **Azure Container Registry** | Stores the versioned Evospaice container image | Yes |
| **Managed identities for Azure resources** | Let jobs read storage, process queue messages, and pull images without stored credentials | Yes |
| **Azure Monitor and Log Analytics** | Store console and system logs and alert on failed or stalled executions | Yes for shared runs |
| **Azure Logic Apps** | Coordinates multiple job stages for recurring or production runs | Optional later |
| **Azure Key Vault** | Stores an external secret only when managed identity cannot be used | Conditional |

This design removes the Azure Batch account and Batch pools. It also does not
require Azure Machine Learning, AKS, Azure Functions, Cosmos DB, Azure SQL, or
a web application for the current file-based workflow.

## 2. Why Container Apps Jobs fits

A Container Apps job starts, runs a finite containerized task, and stops. Job
executions can start manually, on a schedule, or in response to events. This
matches tree construction better than a continuously running web service.

Container Apps Jobs provides:

- scale-to-zero execution for manual and event-driven work;
- configurable CPU, memory, timeout, retry, and parallelism settings;
- Consumption and Dedicated workload profiles;
- queue-driven scaling through KEDA;
- managed identity and private networking; and
- integrated console and system logs.

There is one important limitation: Container Apps Jobs does not provide a
general dependency graph like Azure Batch tasks or an AML pipeline. The
application must make stage completion explicit. Use one job for the MVP, then
use storage manifests plus a small external coordinator when stages are split.

## 3. Azure data flow

### 3.1 MVP: one manual job

```text
Developer or GitHub Actions
  |
  +--> build image -------------------------> Azure Container Registry
  +--> upload run inputs -------------------> ADLS Gen2
  +--> start tree-build job
             |
             v
       Container Apps Job execution
         1. validate IDs, vectors, and policy
         2. build or load the taxonomy backbone
         3. resolve and scale nodes in post-order
         4. verify the completed tree
         5. publish final outputs
             |
             +--> checkpoints and outputs --> ADLS Gen2
             +--> console and system logs ---> Log Analytics
```

Use this path first. It has the fewest moving parts and establishes the real
memory, temporary-storage, and runtime requirements.

### 3.2 Scale-out: queue-driven subtrees

```text
GitHub Actions or Logic Apps
  |
  +--> start prepare job
  |       +--> backbone + partition manifest ----> ADLS Gen2
  |       +--> one message per subtree ----------> Storage Queue
  |
  +--> wait for completion markers
  |                |
  |                v
  |       event-driven subtree-worker job
  |         0..N concurrent job executions
  |         each execution claims one message
  |                |
  |                +--> subtree + diagnostics ---> ADLS Gen2
  |                +--> completion marker --------> ADLS Gen2
  |
  +--> start finalize job only when all expected markers exist
          1. verify the complete partition set
          2. join subtrees and process parent nodes
          3. validate and publish the final tree
```

For the hackathon, GitHub Actions can start jobs and poll their status. For a
recurring production workflow, Logic Apps can perform the same coordination.
Keep the scientific processing inside the Evospaice containers.

## 4. Job definitions

### 4.1 `tree-build`: MVP job

Use one manually triggered job with one replica. It runs the complete pipeline:

```text
validate -> build backbone -> resolve and scale -> verify -> publish
```

Set `parallelism` and `replicaCompletionCount` to `1`. Parallelize carefully
inside the Python process only after measuring memory use. Configure a replica
timeout above the measured end-to-end runtime and keep retries low so a
deterministic data error is not repeatedly executed.

### 4.2 `prepare-tree`: scale-out preparation job

Use one manually triggered replica. It:

1. validates the metadata-to-embedding join;
2. builds the taxonomy backbone;
3. chooses independent subtree boundaries;
4. writes one bounded vector/metadata shard per subtree;
5. writes a partition manifest with expected IDs and checksums; and
6. sends one queue message per partition.

Queue messages contain only `run_id`, `partition_id`, artifact paths, and
checksums. They do not contain embeddings, credentials, or SAS tokens.

### 4.3 `subtree-worker`: event-driven job

Use an event-triggered job connected to Azure Queue Storage through a KEDA
scale rule. Configure managed identity authentication, `minExecutions: 0`, and
a conservative `maxExecutions` value.

Each execution normally uses one replica and processes one queue message. It:

1. receives a partition message;
2. downloads only that partition's files;
3. resolves and scales the subtree;
4. writes results, diagnostics, and a checksum under a stable partition path;
5. writes a completion marker; and
6. deletes the queue message only after durable output is confirmed.

Queue delivery and job retries can cause duplicate processing. The worker must
be idempotent: if a valid result already exists at the stable output path, it
acknowledges the message without rewriting the result. Move repeatedly failing
messages to a poison queue for investigation.

### 4.4 `finalize-tree`: reduce and publication job

Use one manually triggered replica. Before reducing, it compares the partition
manifest with completion markers and checksums. Missing, duplicate, or invalid
partitions fail the job. A valid run then joins the completed subtrees,
processes the upper taxonomy nodes, validates the candidate, and publishes the
final immutable output set.

## 5. Storage design

Create one StorageV2 account with hierarchical namespace enabled for ADLS
Gen2. Use Blob/DFS SDK calls with managed identity; Container Apps does not
mount Blob or ADLS Gen2 as a filesystem.

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
      partition-manifest.json
      partitions/<partition-id>/
      subtree-results/<partition-id>/
      completion/<partition-id>.json
      checkpoints/
    output/
      scaled-tree.nwk
      node-diagnostics.tsv
      excluded-records.tsv
      tree-manifest.json
```

Use a queue such as `tree-subtrees` for partition messages and a separate
`tree-subtrees-poison` queue for exhausted failures. The same StorageV2 account
can host the queues, subject to organisational separation requirements.

Recommended controls:

- keep active inputs and outputs in the Hot tier;
- move old successful runs to Cool storage with lifecycle rules;
- enable blob and container soft delete;
- treat a run directory as immutable after `tree-manifest.json` is written;
- use input, work, and output prefixes to distinguish partial results; and
- verify manifest checksums at every stage boundary.

## 6. Memory and temporary storage

The default Consumption workload profile allows up to 4 vCPU and 8 GiB of
memory per replica. Container-local ephemeral storage is also limited; a
replica allocated more than 1 vCPU has 8 GiB of ephemeral storage.

Use Consumption for the subset only when its measured peak memory and local
scratch fit comfortably inside those limits. For larger runs, add a Dedicated
memory-optimized workload profile and select the smallest tested size that
fits the in-memory tree and local distance blocks.

Dedicated memory does not remove the ephemeral-storage constraint. Keep each
downloaded vector shard plus scratch files below the local limit. Partition
embeddings by independent taxonomy subtree rather than downloading the full
matrix to every execution. Azure Files can provide a persistent mounted
filesystem when unavoidable, but benchmark it before using it for NumPy memory
mapping because it is network storage.

Keep all compute and storage in the same Azure region. Set workload-profile
minimum instances to zero for intermittent runs where supported by the chosen
profile, and bound maximum instances to control cost.

## 7. Container image and deployment

Build one Linux image containing:

- the packaged `evospaice` code;
- pinned Python dependencies;
- all job commands behind the same CLI;
- no datasets, model weights, credentials, or environment-specific values.

Tag every image with an immutable commit SHA and record its digest in the run
manifest. Use a user-assigned managed identity to pull from ACR. Grant
`Container Registry Repository Reader` for an ABAC-enabled registry or
`AcrPull` for a registry using the older RBAC mode. Do not enable anonymous or
administrator access.

Define the Container Apps environment, jobs, identities, role assignments,
storage, queues, registry, and monitoring settings in Bicep under `infra/`.
Changing a job definition affects future executions; the image digest and run
manifest preserve the exact software used by each completed run.

## 8. Identity and security

Prefer separate user-assigned managed identities for coordination and workers
when operational complexity allows it.

| Identity | Minimum data-plane access |
| --- | --- |
| Prepare/finalize job | Read reference/input blobs; write run work/output blobs; send queue messages; pull the image |
| Subtree worker | Read partition blobs; write its result prefix; receive/delete queue messages; authenticate the queue scaler; pull the image |
| CI or Logic Apps coordinator | Start jobs and read execution status; it does not need access to embeddings |

Use built-in roles such as `Storage Blob Data Reader`, `Storage Blob Data
Contributor`, `Storage Queue Data Message Sender`, and `Storage Queue Data
Message Processor`, scoped as narrowly as practical.

Permission to start a Container Apps Job can be security-sensitive because the
start API can override container commands and environment variables. Grant
`Microsoft.App/jobs/start/action` only to trusted identities. Avoid broad
wildcard job permissions when a custom least-privilege role is appropriate.

Do not place storage keys, queue connection strings, SAS tokens, or registry
passwords in job settings. Use managed identity for both the queue scale rule
and application SDK access. Use Key Vault only for a third-party secret that
cannot use identity-based authentication.

For a secured deployment, use a workload profiles environment connected to a
virtual network, private endpoints for Blob, DFS, Queue, and ACR, private DNS,
and restricted public network access according to organisational policy. The
jobs require no HTTP ingress.

## 9. Monitoring and recovery

Send Container Apps console and system logs to Log Analytics. Include
`run_id`, `stage`, `partition_id`, and image digest in every structured log
record so concurrent executions can be correlated.

Record these application measures:

- accepted and rejected record/vector counts;
- expected, queued, running, completed, and failed partitions;
- largest child count and local distance matrix;
- elapsed time and peak memory by stage;
- NJ, NNLS, medoid, and branch-clamp fallback counts;
- checkpoint and output paths; and
- final tree and manifest checksums.

Alert on failed executions, poison-queue messages, a queue with no processing
progress, missing completion markers, and runs exceeding their expected
duration. The portal retains only a limited recent execution history for some
job types, so Log Analytics and the run manifest are the durable operational
record.

Set a small retry limit. Retry transient node and storage failures, but do not
retry deterministic validation or algorithm failures. Stable partition IDs,
checksums, and idempotent writes let replacement executions reuse completed
work safely.

## 10. Cost controls

- Start with the Consumption profile and one manual job when measurements fit.
- Set event-driven workers to `minExecutions: 0`.
- Set a hard `maxExecutions` limit for the queue-triggered worker.
- Use a Dedicated profile only when the measured memory requirement exceeds
  Consumption limits or sustained load makes it more economical.
- Set Dedicated minimum instances to zero for intermittent workloads where
  supported by the selected profile.
- Split work that approaches the replica timeout or temporary-storage limit.
- Apply lifecycle rules to checkpoints, logs, and old runs.
- Keep compute, ACR, and storage in the same region.
- Create Azure budgets and alerts before a full-scale test.

## 11. MVP and full-scale service sets

### Hackathon MVP

Provision:

1. one Container Apps workload profiles environment using Consumption;
2. one manually triggered `tree-build` Container Apps Job;
3. one ADLS Gen2 Storage account;
4. one Azure Container Registry;
5. one user-assigned managed identity; and
6. one Log Analytics workspace with Azure Monitor alerts.

Run the complete subset tree in one job execution. Move to a Dedicated
memory-optimized profile immediately if the measured subset cannot fit within
Consumption memory or temporary-storage limits.

### Full-scale candidate

Keep the core resources, then add:

- the `prepare-tree`, `subtree-worker`, and `finalize-tree` jobs;
- Storage Queue and poison queue;
- queue-driven KEDA scaling with managed identity;
- a Dedicated memory-optimized workload profile if measurements require it;
- private endpoints and tighter storage scopes; and
- Logic Apps only when recurring production orchestration is needed.

Do not add Azure Batch or Azure Machine Learning unless measured Container Apps
limits make the workload unsuitable. Reconsider Batch for extreme HPC
scheduling, very large local disks, or a much larger dependency graph.

## 12. Service choices by workstream

| Workstream | Azure services |
| --- | --- |
| WS0 - Foundation | Container Apps environment, ACR, managed identities, Log Analytics, and Bicep |
| WS1 - Ingest and backbone | ADLS Gen2 and the `prepare-tree` or MVP job |
| WS2 - Precomputed vectors | ADLS Gen2 for the tree scope; optional Container Apps GPU profile if embeddings must be regenerated |
| WS3 - Tree building | Manual and event-driven Container Apps Jobs, ADLS Gen2, Queue Storage, and ACR |
| WS4 - Validation | The `finalize-tree` job reading candidate trees and references from ADLS Gen2 |
| WS5 - Integration and scale | Queue scaling, completion manifests, Azure Monitor, budgets, and optional Logic Apps |
| WS6 - Visualisation | Local tools or a separate finite Container Apps Job that publishes approved static artifacts |
| WS7 - Diversity and curation | Optional Container Apps Jobs reading approved tree artifacts |
| WS8 - Demo and decision | ADLS Gen2 output package and Container Apps execution/log evidence |

## 13. Official guidance

- [Jobs in Azure Container Apps](https://learn.microsoft.com/azure/container-apps/jobs)
- [Deploy an event-driven Container Apps job](https://learn.microsoft.com/azure/container-apps/tutorial-event-driven-jobs)
- [Set scaling rules in Azure Container Apps](https://learn.microsoft.com/azure/container-apps/scale-app)
- [Workload profiles in Azure Container Apps](https://learn.microsoft.com/azure/container-apps/workload-profiles-overview)
- [Use managed identities in Azure Container Apps](https://learn.microsoft.com/azure/container-apps/managed-identity)
- [Pull ACR images with managed identity](https://learn.microsoft.com/azure/container-apps/managed-identity-image-pull)
- [Use storage mounts in Azure Container Apps](https://learn.microsoft.com/azure/container-apps/storage-mounts)
- [Monitor Container Apps logs with Log Analytics](https://learn.microsoft.com/azure/container-apps/log-monitoring)
- [Azure Data Lake Storage introduction](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-introduction)
- [Blob Storage lifecycle management](https://learn.microsoft.com/azure/storage/blobs/lifecycle-management-overview)
