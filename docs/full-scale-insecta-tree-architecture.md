# Full-scale Insecta tree architecture

## 1. Current production input

The embedding export currently exists at:

```text
Storage account: mlstaiseqhacke1lkzk
Container:       embedding-results
Prefix:          insecta/0x8df1258ad040f84/
```

The prefix is versioned with the ETag of the source FASTA. It contains:

| Artifact | Observed size | Meaning for the tree pipeline |
| --- | ---: | --- |
| `records.parquet` | 346,222,372 bytes | Metadata for 6,979,067 embedded records. `faiss_id` is the join key declared by the manifest. Its taxonomy and BIN columns must still be validated. |
| `index.faiss` | 7,202,397,234 bytes | `IndexIDMap2(IndexFlatIP)` containing the exact 256-dimensional `float32` vectors and their FAISS IDs. Vectors are L2-normalised, so inner product is cosine similarity and tree distance is `1 - similarity`. |
| `manifest.json` | 919 bytes | Immutable source, model, row-count, vector-shape, metric, filename, and SHA-256 provenance. It is an embedding manifest, not the final tree manifest. |

The source was a 3,279,290,758-byte `insecta.fasta`. The embedding manifest
records model `zehui127/Omni-DNA-20M`, revision
`3b64e6a5ed6c8f72bad76823ce728b3045243026`, 6,979,067 records, and vector
dimension 256.

`index.faiss` is not a precomputed phylogenetic tree or a global distance
matrix. `IndexFlatIP` stores every vector exactly and supports nearest-neighbour
queries. The tree pipeline must reconstruct the selected vectors by `faiss_id`
and combine them with BIN and taxonomy metadata from `records.parquet`.

## 2. Why the MVP architecture no longer fits

The current implementation and Bicep describe one Container Apps Consumption
job that downloads `records.tsv`, `embeddings.npy`, `embedding-index.tsv`, and
`trust-policy.json` into local temporary storage. A Consumption replica is
limited to 8 GiB memory and, for replicas above 1 vCPU, 8 GiB ephemeral storage.
The production input is a different format and is already approximately 7.55
GB before temporary files or outputs.

The raw vector payload alone is:

$$
6{,}979{,}067 \times 256 \times 4 = 7{,}146{,}564{,}608\ \text{bytes}.
$$

Loading the FAISS index, ID map, taxonomy graph, Python records, representatives,
and local distance blocks cannot fit into an 8 GiB replica. The current builder
also retains a `float64` representative for every processed leaf and builds the
whole taxonomy graph in memory. That approach must not be used for 6.98 million
records.

A global pairwise distance matrix is forbidden. At `float64`, it would require
approximately:

$$
(6{,}979{,}067)^2 \times 8 \approx 390\ \text{TB}.
$$

Distances must remain local to bounded taxonomy nodes or bounded clustering
batches.

## 3. Recommended Azure architecture

Retain Azure Container Apps Jobs, but move from the one-replica MVP to a
partitioned map/reduce workflow on a Dedicated memory-optimised workload
profile.

```text
mlstaiseqhacke1lkzk / embedding-results       (existing, read-only landing zone)
  records.parquet + index.faiss + manifest.json
                         |
             operator-authenticated copy
             (read old, write new; no old-RG RBAC)
                         |
                         v
            rg-evoispace-tree-lp work lake
                         |
                 prepare-tree job
          validate -> select BIN representatives
          -> build backbone -> make bounded shards
                         |
              +----------+-----------+
              |                      |
              v                      v
       ADLS Gen2 work lake      Storage Queue
       partition manifest       one message per shard
       metadata/vector shards          |
              |                       v
              +------------ subtree-worker jobs (0..N)
                              bounded shard per execution
                                      |
                                      v
                              subtree results,
                              representatives,
                              diagnostics, markers
                                      |
                                      v
                              finalize-tree job
                              verify all markers
                              reduce upper tree
                              validate and publish
```

The existing source account is `StorageV2`, Standard LRS, in Sweden Central.
It has hierarchical namespace disabled, shared-key access disabled, OAuth as
the default, and private containers behind an enabled public endpoint. Keep it
as the read-only system of record. To avoid any resource or RBAC change in
`rg-ai-seq-h3-hack-e1lkzk`, an authenticated operator copies the three blobs to
the new work lake before execution. Jobs never access the old resource group.

Create a separate HNS-enabled ADLS Gen2 account for tree work, checkpoints, and
published outputs. This separates immutable ML outputs from retryable tree work
and permits directory ACLs and lifecycle policies. Keep the new account,
Container Apps environment, and registry in Sweden Central to avoid cross-region
transfer.

## 4. Azure service changes

| Service | Change from the current Bicep | Why |
| --- | --- | --- |
| Existing Blob account `mlstaiseqhacke1lkzk` | Read the three versioned blobs with the operator's existing identity and stage copies in the new work lake; create no resources or RBAC assignments in the old group | This strictly preserves `rg-ai-seq-h3-hack-e1lkzk` while giving jobs access inside their own security boundary. |
| New ADLS Gen2 work account | Keep the separately provisioned HNS-enabled account, but use it only for partitions, checkpoints, queues, and final outputs | The existing ML account has no hierarchical namespace and should remain an immutable landing zone. |
| Azure Container Apps environment | Add a Dedicated memory-optimised workload profile; retain Consumption only for small coordinator or publication work | The full FAISS adapter and preparation stage exceed Consumption memory and scratch limits. |
| Container Apps Jobs | Replace one `tree-build` job with `prepare-tree`, event-driven `subtree-worker`, and `finalize-tree` jobs | Independent taxonomy subtrees must be bounded, checkpointed, and processed in parallel. |
| Azure Queue Storage | Add `tree-subtrees` and `tree-subtrees-poison` queues with a managed-identity KEDA scale rule | Provides durable work distribution, scale to zero, retries, and failure isolation. |
| Coordinator | Use a small coordinator job for the first run; use Logic Apps for recurring production runs | Container Apps Jobs has no native dependency graph. Finalize must start only after every expected marker is valid. |
| Azure Container Registry | Retain it, but use an immutable image digest and include `pyarrow`, `faiss-cpu`, Azure SDKs, and the tree code | The production adapter must stream Parquet and read FAISS. |
| Managed identities and RBAC | Separate prepare/finalize and worker identities where practical | Source reads, work writes, queue processing, and job-start permissions have different scopes. |
| Log Analytics and Azure Monitor | Add stage duration, rows/shards processed, memory, disk, queue depth, poison messages, and stalled-run alerts | Failures in a multi-job run must be diagnosable without inspecting local disks. |

Azure Machine Learning is not required merely because the input is an ML
artifact, and GPU compute is not required to construct the tree. Azure Batch is
a reasonable alternative if tests show that Container Apps Dedicated profiles
cannot provide the required local SSD, memory size, or task scheduling. Do not
operate Container Apps Jobs and Azure Batch for the same tree workflow.

## 5. Additional application components

### 5.1 Embedding export adapter

Add a streaming adapter that:

1. verifies the two SHA-256 values and all fields in `manifest.json`;
2. reads only the required columns from `records.parquet` into an Arrow table;
3. validates that `faiss_id` is unique and covers the FAISS ID map exactly;
4. reconstructs vectors from `index.faiss` for selected IDs;
5. preserves the declared normalisation and cosine metric; and
6. writes an immutable validation report.

Blob Storage is not a POSIX filesystem. Download `index.faiss` once to the
prepare replica's attached/local disk before opening it. Do not make every
worker download the 7.2 GB monolith.

### 5.2 Metadata and one-tip-per-BIN validation

The production Parquet schema was inspected on 2026-09-14. It has 6,979,067
rows in 426 row groups and these columns:

```text
faiss_id, source_record_number, record_id, header, sequence,
kingdom, phylum, class, order, family, genus, species, source_blob_url
```

It has no `leaf_id`, `bin_uri`, or other BIN column, and sampled headers do not
contain BIN identifiers. The prepare stage therefore requires a versioned
`record-bin-map.parquet` with exactly one non-null mapping for every embedded
record:

```text
record_id: string
bin_uri:   string
```

Preparation fails before opening the 7.2 GB FAISS index when this mapping is
missing, incomplete, duplicated, or contains null/empty BINs. It selects the
lowest `faiss_id` deterministically for each BIN. The final tree contains one
`leaf_id` per BIN rather than 6.98 million sequence records.

### 5.3 Partition planner and shard writer

Build the taxonomy backbone from the selected records and choose order, family,
or another measured boundary so every shard fits the worker memory and scratch
budget. Write one shard containing compact metadata and vectors for that
independent subtree. The partition manifest records:

- run ID, source ETag, source and shard checksums;
- partition ID and taxonomy root;
- expected leaf and vector counts;
- parent partition relationship;
- vector dimension and metric;
- software/image digest; and
- expected result and completion-marker paths.

Use a bounded target based on measured peak memory, not a fixed taxonomic rank.
Split exceptional high-fanout groups further.

### 5.4 Stateless subtree worker

A worker downloads one shard, builds one subtree, and uploads:

- a Newick subtree or compact tree sidecar;
- one representative vector for its root;
- diagnostics and exclusions;
- a result manifest with checksums; and
- a completion marker written last.

Workers must be idempotent because queue messages are delivered at least once.
A retry accepts an existing result only when its checksums and configuration
match. Repeated failures move to the poison queue.

### 5.5 Reducer and publisher

The reducer verifies that the partition manifest and completion markers match,
then reads subtree roots and root representatives rather than all leaf vectors.
It resolves the upper taxonomy tree, validates tip counts and branch lengths,
and writes `tree-manifest.json` last as the publication marker.

### 5.6 Disk-backed tree state

Replace the current all-in-memory record, graph, representative, and diagnostic
stores with streaming or disk-backed stores. Representatives should be released
when their parent has been completed, except for partition roots needed by the
reducer. Check fanout before allocating a square distance block; a node above
the configured limit must be split or preserved as a star without first
constructing its $O(k^2)$ matrix.

## 6. Work-lake layout

```text
tree-runs/
  reference/
    embedding-exports/insecta/0x8df1258ad040f84/source-pointer.json
  runs/<tree-run-id>/
    input/
      embedding-manifest.json
      trust-policy.json
      selection-policy.json
    prepare/
      validation-report.json
      selected-records.parquet
      backbone.nwk
      partition-manifest.json
      partitions/<partition-id>/metadata.parquet
      partitions/<partition-id>/vectors.npy
    work/
      subtree-results/<partition-id>/subtree.nwk
      subtree-results/<partition-id>/representative.npy
      subtree-results/<partition-id>/diagnostics.parquet
      completion/<partition-id>.json
      checkpoints/
    output/
      scaled-tree.nwk
      node-diagnostics.parquet
      excluded-records.parquet
      validation-report.json
      tree-manifest.json
```

Keep active data Hot. Apply lifecycle rules to abandoned shards and old
checkpoints, while retaining source pointers, final trees, and manifests under
the project's scientific retention policy.

## 7. Sizing and rollout

Do not select production resources from file size alone. Benchmark these stages
separately and record peak resident memory, local disk, elapsed time, and bytes
transferred:

1. schema and checksum validation without loading the FAISS index;
2. FAISS load plus vector reconstruction for a measured ID sample;
3. deterministic representative selection for several large BINs;
4. one small, one median, and one largest taxonomy partition;
5. upper-tree reduction using synthetic completed partitions; and
6. end-to-end execution on a small set of partitions.

Start the prepare job on a Dedicated profile with enough memory for the 7.2 GB
index plus at least a measured safety margin and with local/attached storage
well above the input plus largest output shard. Size workers independently from
the maximum permitted partition. Bound worker concurrency by both the Azure
quota and storage throughput; increasing replicas past the storage bottleneck
only increases cost.

The first full run is ready only after these gates pass:

- the Parquet schema and `faiss_id` coverage are proven;
- one deterministic record per BIN is selected, or the different leaf model is
  explicitly approved;
- taxonomy and `trust-policy.json` are versioned inputs;
- partition recovery and duplicate queue delivery are tested;
- the largest shard fits with safety margin;
- finalize rejects missing, duplicate, or mismatched completion markers; and
- the output tip count and checksums reconcile to the selection manifest.
