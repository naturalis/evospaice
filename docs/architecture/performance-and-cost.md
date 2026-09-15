# Performance and cost

## Measured production runs

### Class filtering

Input:

- BOLD Leray FASTA: 3,433,357,098 bytes

Output:

- Insecta FASTA: 3,279,290,758 bytes
- Records: 6,979,067

The Function streams both input and output and uses one concurrent invocation.

### Omni-DNA embedding

- Compute: one dedicated `Standard_NC24ads_A100_v4` node
- Records: 6,979,067
- Vector dimension: 256
- Runtime: approximately 20 minutes
- Global FAISS index: 7,202,397,234 bytes
- Parquet metadata: 346,222,372 bytes

Observed inference throughput was roughly 5,900 to 6,200 records per second after
startup.

### Species splitting

Initial single-node partitioning was projected to take hours because it created
and reread many temporary partitions and serialized hundreds of thousands of
small blobs.

The optimized implementation uses:

- eight deterministic hash shards
- up to eight dedicated `Standard_D16ds_v5` nodes
- Arrow dictionary encoding for species keys
- node-local temporary partitions
- parallel writes through a shared Blob mount

Measured sharded production:

- Records: 6,979,067
- Species bundles: 131,914
- Final files: 395,742
- Compute/write phase: approximately 3 minutes
- Failed shards: zero

The flat-folder migration preserves this sharded compute model while uploading
all globally unique species files into one version folder.

## Cost drivers

Azure prices vary by agreement, region, and date. Use the Azure Pricing Calculator
or Cost Management for authoritative amounts.

Primary drivers are:

- dedicated A100 node minutes for embedding
- eight D16ds v5 node minutes for species splitting
- Flex Consumption Function executions
- Service Bus Standard namespace uptime
- Blob capacity for source, global, and per-species data
- Blob transaction count, especially three files per species
- Log Analytics ingestion and retention

Approximate compute cost formulas:

$$
C_{embed} = P_{A100/hour} \times \frac{T_{embed\ minutes}}{60}
$$

$$
C_{split} = 8 \times P_{D16ds\ v5/hour} \times \frac{T_{split\ minutes}}{60}
$$

Both AML clusters have minimum node count zero and scale down after ten idle
minutes. That idle window should be included when reconciling billed compute.

## Capacity planning

- Global FAISS memory footprint is about 7.2 GB.
- Each 64 GB splitter node has sufficient memory for one global index plus Arrow
  batches and local partitions.
- Eight shards currently require 128 dedicated DDSv5 family vCPUs.
- The validated AML quota was 350 dedicated DDSv5 family vCPUs.
- The species output creates many small blobs; storage transaction latency can
  dominate after compute finishes.

## Progress telemetry

Each species worker reports structured JSON containing:

- stage: index load, partition, or species write
- shard index and shard count
- completed and total units
- percentage
- elapsed seconds
- current rate
- estimated seconds remaining
- selected or written record count

Estimate completion from the slowest shard, then add AML output-finalization time.
