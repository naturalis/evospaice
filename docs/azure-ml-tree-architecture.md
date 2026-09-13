# Azure Machine Learning architecture for building the tree

> **Alternative design:** The project has selected Azure Container Apps Jobs
> as the execution platform. See the
> [Container Apps Jobs tree architecture](azure-container-apps-tree-architecture.md).
> This document remains as the Azure Machine Learning alternative.

## 1. Short answer

Yes. Azure Machine Learning (AML) can replace the separately managed compute
and orchestration services in the earlier design.

| Existing choice | AML-first replacement | Result |
| --- | --- | --- |
| Azure Batch account and pools | AML pipeline jobs plus AML compute clusters | Remove the direct Azure Batch resources |
| Azure Data Factory for internal orchestration | AML pipeline job dependencies and schedules | Remove Data Factory unless it coordinates systems outside AML |
| Azure Container Apps Jobs | AML command and parallel components | Remove Container Apps Jobs from this workflow |
| Standalone run-tracking solution | AML job history and MLflow metrics/artifacts | Use AML for scientific run tracking; keep Azure Monitor for platform operations |
| Manually operated ACR | AML environments backed by the workspace-associated ACR | ACR still exists, but AML manages how job images use it |
| Standalone artifact storage | AML default Blob storage for an MVP, or an attached ADLS Gen2 datastore for larger data | Storage still exists; AML does not store large files inside the workspace itself |

AML does **not** replace identity, durable storage, container storage, or
monitoring. It provides one control plane over those resources.

## 2. Recommended service set

### Minimum hackathon setup

| Azure service | Purpose |
| --- | --- |
| **Azure Machine Learning workspace** | Defines components and environments, runs pipelines, tracks jobs, logs, metrics, code snapshots, inputs, and outputs |
| **AML CPU compute cluster** | Runs the tree-building components; use a memory-optimized VM family and set minimum nodes to zero |
| **Workspace Storage account** | Stores AML system artifacts and can store the subset input/output files for the MVP |
| **Workspace Azure Container Registry** | Stores container images built from AML environments |
| **Workspace Key Vault** | Supports workspace secrets and connections; application code should still prefer managed identity |
| **Application Insights / Azure Monitor** | Provides workspace and platform diagnostics |
| **User-assigned managed identity** | Gives compute controlled access to storage and other Azure resources |

The workspace can create its associated Storage, ACR, Key Vault, and
Application Insights resources. They remain real Azure resources, but the team
does not need to build separate application-level integrations for each one.

### Add for larger data

Add a separate **ADLS Gen2** account and register it as an AML datastore when
the project needs hierarchical directories, path-level ACLs, long-term data
lake retention, or separation between workspace internals and scientific data.

An AML workspace's default Storage account cannot have hierarchical namespace
enabled. Therefore:

- use the workspace's normal Blob storage alone for the simplest MVP; or
- keep the workspace's required default storage and attach ADLS Gen2 as a
  second datastore for production data.

## 3. AML pipeline

Build the workflow as reusable AML v2 components:

```text
records + embeddings + index + policy
                  |
                  v
        validate-inputs (command)
                  |
                  v
         build-backbone (command)
                  |
                  v
       partition-subtrees (command)
                  |
                  v
       resolve-subtrees (parallel)
                  |
                  v
          reduce-tree (command)
                  |
                  v
      verify-and-publish (command)
                  |
                  +--> scaled-tree.nwk
                  +--> node-diagnostics.tsv
                  +--> excluded-records.tsv
                  +--> tree-manifest.json
```

Use a **command component** for steps that run once. Use an AML **parallel
component** for independent taxonomy subtrees. Pipeline input/output bindings
create the dependencies, so a downstream step starts only when its required
upstream output is ready.

### Component contracts

| Component | Inputs | Outputs |
| --- | --- | --- |
| `validate-inputs` | `records.tsv`, `embeddings.npy`, `embedding-index.tsv`, policy | Validated index, exclusion report, input summary |
| `build-backbone` | Validated records | `backbone.nwk`, sidecar, backbone report |
| `partition-subtrees` | Backbone, embedding index, compute limits | Partition manifest and one vector/metadata shard per independent subtree |
| `resolve-subtrees` | Partition folder, policy, tree environment | Completed subtree files, root representatives, diagnostics, checkpoints |
| `reduce-tree` | Backbone plus all completed subtree outputs | Combined and parent-resolved candidate tree |
| `verify-and-publish` | Candidate tree, input summary, policy | Final tree, final diagnostics, exclusions, manifest |

Register stable component versions in the AML workspace. Pin each pipeline run
to exact component and environment versions so later runs remain reproducible.

## 4. Data assets and access modes

Register the following as versioned AML data assets or pass them as versioned
job inputs:

- linked metadata and embedding index;
- embedding matrix or partitioned vectors;
- trust policy;
- trusted validation tree; and
- small test fixtures.

Use `uri_file` for a single file and `uri_folder` for partitioned data. The
large vector input should use **download mode** when the code needs NumPy memory
mapping. This places the file on compute-local storage before processing.
Remote object storage cannot be treated as a reliable local memory-mapped file.

For the scale-out path, write one file or directory per independent taxonomy
subtree. The parallel component can then distribute those partitions as
mini-batches without downloading the complete embedding matrix to every node.

Write final files to a named pipeline output path. AML also records the job,
component versions, environment, parameters, logs, and output references. Keep
the Evospaice `tree-manifest.json` because it records domain details that AML
does not know, such as leaf counts, taxonomy policy, solver settings, and file
checksums.

## 5. Compute design

### Start with one CPU cluster

Create one AML compute cluster:

- current supported Linux image;
- memory-optimized VM size selected after a local benchmark;
- `min_instances: 0` so idle compute deallocates;
- a small `max_instances` limit for the first run;
- user-assigned managed identity; and
- the same Azure region as the data.

Run all command components and the first end-to-end subset on this cluster.
This proves memory and runtime requirements before adding complexity.

### Scale independent subtrees

Increase `max_instances` and use an AML parallel component when subtrees become
the bottleneck. Configure:

- one partition per mini-batch or a measured number of subtrees per mini-batch;
- bounded process count per node;
- explicit mini-batch timeout and retry count;
- low failure thresholds rather than defaults that tolerate every failure; and
- resource monitoring at a useful interval.

The final `reduce-tree` component remains a single job because it joins subtree
roots and processes the upper tree. More workers do not speed up this serial
part.

### Optional second clusters

- Add a low-priority/Spot CPU cluster only for retryable subtree work.
- Add a GPU cluster only if embedding generation moves into this AML pipeline.

Do not use a compute instance for production jobs. It is a development
workstation, not the pipeline execution target.

## 6. Environment and container image

Define one versioned AML environment from the project's container/Dockerfile or
from a pinned base image plus Conda dependencies. The environment contains code
dependencies, not data or credentials.

AML builds custom environments into the workspace-associated ACR. Record the
resolved environment version and image digest in the tree manifest. This keeps
the same runtime repeatable across command and parallel components.

The code should remain runnable outside AML. Each component command calls the
normal Evospaice CLI with file paths supplied by AML, for example:

```text
python -m evospaice.tree.pipeline \
  --records ${{inputs.records}} \
  --embeddings ${{inputs.embeddings}} \
  --index ${{inputs.embedding_index}} \
  --policy ${{inputs.policy}} \
  --output ${{outputs.tree}}
```

AML is the orchestrator, not a dependency of the core tree algorithms.

## 7. Identity and network security

Assign a user-managed identity to the AML compute cluster. Grant only:

- `Storage Blob Data Reader` on immutable inputs;
- `Storage Blob Data Contributor` on the run-output location; and
- access required by AML to use the workspace's associated resources.

Do not pass account keys or SAS tokens through component arguments. Use
identity-based datastores and `DefaultAzureCredential` or the identity selected
by the AML job when code must call Azure APIs directly.

For a secured production workspace, use AML managed network isolation or a
customer-managed virtual network, private endpoints for Storage, Key Vault, and
ACR, and disable public access according to organisational policy. Keep all
workspace-associated resources in compatible regions and network boundaries.

## 8. Tracking and monitoring

Use AML job history and MLflow for scientific and execution-level tracking:

- input data and policy versions;
- component and environment versions;
- child counts and completed node counts;
- branch-fit error distributions;
- NJ, NNLS, medoid, and clamp counts;
- elapsed time and peak resource use; and
- final quality checks.

Store large tree files and diagnostics as job outputs rather than individual
MLflow metrics. Use Azure Monitor and workspace diagnostics for infrastructure
failures, audit logs, quota problems, and operational alerts.

AML job tracking reduces the amount of custom run-tracking code, but it does
not replace `node-diagnostics.tsv` or `tree-manifest.json`. Those files are the
portable scientific record and remain usable outside Azure.

## 9. Scheduling and external orchestration

Use AML pipeline schedules when the tree build runs on a timetable. This
replaces Data Factory for an AML-only workflow.

Keep Data Factory only if it must coordinate external ingestion, data movement,
or downstream systems that are not represented as AML components. In that
case, Data Factory should trigger one AML pipeline job and monitor its status,
not duplicate the internal stage graph.

## 10. Cost controls

- Set every AML compute cluster's minimum node count to zero.
- Set conservative maximum node counts and workspace/subscription quotas.
- Use low-priority/Spot nodes only for checkpointed, retryable subtree work.
- Configure job timeouts and cancellation rules.
- Keep compute and data in the same region.
- Use lifecycle rules for old job outputs and checkpoints.
- Avoid registering every temporary shard as a long-lived data asset.
- Benchmark the single-node pipeline before enabling the parallel component.
- Create Azure budgets and alerts before a full-scale run.

## 11. What AML replaces and what remains

### Remove from the previous design

- The directly managed Azure Batch account and pools.
- Container Apps Jobs for tree stages.
- Data Factory for internal pipeline dependencies and scheduling.
- A custom database or service for run history.

### Keep, but let AML integrate it

- Azure Storage for files and job artifacts.
- Azure Container Registry for custom environment images.
- Key Vault as a workspace-associated security resource.
- Managed identity and Azure RBAC.
- Application Insights and Azure Monitor for platform diagnostics.

### Add only when justified

- ADLS Gen2 as an attached datastore for larger or governed scientific data.
- A low-priority CPU cluster for retryable parallel subtree work.
- A GPU cluster for embedding generation.
- Data Factory for orchestration outside AML.

## 12. Recommended MVP resources

Provision:

1. one Azure Machine Learning workspace;
2. its standard default Storage account;
3. its workspace-associated Key Vault, ACR, and Application Insights;
4. one user-assigned managed identity; and
5. one autoscaling, memory-optimized AML CPU compute cluster.

Use the workspace's default storage for the first subset. Add ADLS Gen2 only
after data size, governance, or path-level access requirements justify the
second storage account.

## 13. Official guidance

- [Azure Machine Learning workspaces and associated resources](https://learn.microsoft.com/azure/machine-learning/concept-workspace)
- [Azure Machine Learning pipeline concepts](https://learn.microsoft.com/azure/machine-learning/concept-ml-pipelines)
- [Create component pipelines with CLI v2](https://learn.microsoft.com/azure/machine-learning/how-to-create-component-pipelines-cli)
- [Use parallel jobs in pipelines](https://learn.microsoft.com/azure/machine-learning/how-to-use-parallel-job-in-pipeline)
- [Create an AML compute cluster](https://learn.microsoft.com/azure/machine-learning/how-to-create-attach-compute-cluster)
- [Identity-based authentication between AML and other services](https://learn.microsoft.com/azure/machine-learning/how-to-identity-based-service-authentication)
- [Manage and optimise AML costs](https://learn.microsoft.com/azure/machine-learning/how-to-manage-optimize-cost)
- [Use datastores](https://learn.microsoft.com/azure/machine-learning/how-to-datastore)
