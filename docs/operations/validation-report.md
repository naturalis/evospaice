# Pipeline validation report

## Scope

This report records the hack-environment validation performed for class
filtering, Omni-DNA embedding, FAISS/Parquet serialization, and species splitting.

## Class filter

Source:

```text
BOLD/20260327/cropped/BOLD_Public_27-Mar-2026_leray.fasta
```

The source BOLD headers use `c__Insecta`. The parser was validated against a
100 MiB range sample:

- complete records inspected: 218,051
- Insecta records: 218,051
- non-insect records: 0
- one truncated boundary header excluded

Full output:

- blob: `filtered-sequences/insecta.fasta`
- bytes: 3,279,290,758
- records: 6,979,067

## Embedding smoke test

A two-record FASTA containing `Danaus plexippus` and `Musca domestica` completed
on the dedicated A100 cluster.

Validated outputs:

- two vectors
- 256 dimensions
- normalized `IndexIDMap2(IndexFlatIP)`
- Parquet metadata with both FASTA records
- source ETag and model revision in the manifest
- matching SHA-256 checksums

## Embedding production run

Job:

```text
embed-insecta-e6d70de032df
```

Results:

- status: Completed
- errors: none
- runtime: approximately 20 minutes
- records/vectors: 6,979,067
- FAISS bytes: 7,202,397,234
- Parquet bytes: 346,222,372
- model revision: `3b64e6a5ed6c8f72bad76823ce728b3045243026`

## Species splitter smoke tests

The two-record bundle validated:

- deterministic species hashing
- unknown-species routing
- preservation of global FAISS IDs
- one `.faiss`, `.parquet`, and `.json` file per species
- matching manifest checksums
- no temporary partition files in result storage
- concurrent shard writes through a shared Blob mount

## Species splitter production run

Eight shard jobs completed successfully:

```text
split-species-78f0c86b7a6d-s000 through s007
```

Results:

- completed shards: 8
- failed shards: 0
- records reconciled: 6,979,067
- species bundles: 131,914
- `.faiss` files: 131,914
- `.parquet` files: 131,914
- `.json` files: 131,914
- total files: 395,742
- unknown files: 3
- temporary artifacts: 0
- dead-letter messages: 0

The sharded worker emitted structured partition and species-write telemetry,
including rates and ETA.

## Data reconciliation

Production Parquet checks:

- rows: 6,979,067
- unique `faiss_id` values: 6,979,067
- minimum ID: 0
- maximum ID: 6,979,066
- species groups including unknown: 131,914
- unknown species records: 4,983,941

See [species-record-counts.md](species-record-counts.md) for the complete sorted
species count table.

## Infrastructure validation

- Terraform formatting passed.
- Terraform provider validation passed.
- Applied plans were reviewed for replacements and destroys.
- Final Terraform refresh reported no drift.
- Function queues were empty with zero dead letters after completed runs.
- AML compute clusters scaled from zero and completed without unusable nodes.
