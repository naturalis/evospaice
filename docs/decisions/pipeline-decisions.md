---
title: Pipeline Decisions
description: Recorded decisions for the embedding model, source database, filters, and primer-window cropping
author: EvoSpaice team
ms.date: 2026-09-15
ms.topic: reference
keywords:
  - decisions
  - omni-dna
  - bold
  - filters
  - primer window
estimated_reading_time: 4
---

This record captures the settled choices behind the ingest and embedding pipeline, with the reasoning and the authoritative docs for each. Values here reflect the current production run.

## Embedding model: Omni-DNA 20M

Decision: embed every retained record with the public `zehui127/Omni-DNA-20M` checkpoint (MIT licensed), pinned to revision `3b64e6a5ed6c8f72bad76823ce728b3045243026`. The model produces a 256-dimensional hidden state; the stored vector is an attention-mask-weighted mean over tokens, cast to float32 and L2-normalized. Inputs are truncated to 1,024 tokenizer tokens and processed in batches of 256 on the `Standard_NC24ads_A100_v4` A100 cluster.

Rationale: this is the encoder already validated in the AML workspace, and it agrees closely with BLAST for identification. Because vectors are L2-normalized, `IndexFlatIP` inner product equals cosine similarity, so Track 1 emits vectors and downstream work computes distances on demand without a global matrix.

Caveat: BLAST-agreement certifies retrieval, not a calibrated additive metric. Depth-faithfulness, additivity, and tip-compression must be validated separately.

References: [omni-dna-model.md](../architecture/omni-dna-model.md), [parquet-metadata-format.md](../architecture/parquet-metadata-format.md).

## Source database: BOLD

Decision: use a BOLD public data package in BCDM-TSV format as the source of sequences and taxonomy. The production embedding run used the BOLD Public release cropped to the Leray window, filtered to class Insecta, yielding 6,979,067 records. The taxonomy-derived BIN scaffold was built for phylum Arthropoda.

Rationale: BOLD is the reference collection for COI barcodes at the scale this project targets, and BCDM-TSV carries both the Linnaean taxonomy and the BIN assignment each later stage depends on. Scope was narrowed to insects in line with the hackathon's fixed scope.

Scale: of 23,954,047 records in the dump, 17,617,788 Arthropoda records with a BIN went into the scaffold; the Insecta embedding run produced 6,979,067 vectors.

References: [data/README.md](../../data/README.md), [validation-report.md](../operations/validation-report.md), [species-record-counts.md](../operations/species-record-counts.md), [data-contracts.md](../architecture/data-contracts.md).

## Filters

Decision: apply three filters before embedding.

* Class filter: keep only records whose taxonomy class matches the requested target (Insecta). Records with no class metadata are dropped.
* Marker filter: keep only COI-5P records, since BIN identity and primer-window scoring are meaningful only for that marker.
* Dereplication: keep one representative record per BIN (`bin_uri`), collapsing near-identical copies within a taxon and never across taxa.

Optional quality gates (off by default) can hard-reject candidates below a minimum sequence length or above a maximum ambiguity fraction.

Rationale: within-taxon dereplication is deliberate bias mitigation, not cleanup. A global dedup would merge two different species that happen to share an identical window into one mislabeled leaf, so collapsing happens inside each taxonomic group.

References: [ingest/README](../../src/evospaice/ingest/), `filter_bcdm_bin_representatives.py`, [data-contracts.md](../architecture/data-contracts.md).

## Primer-window cropping

Decision: crop each record to the Leray-313 COI window before embedding. The default primer set is `leray` (forward-only, roughly 313 bp). Primer search tries an exact IUPAC match first, then a mismatch-tolerant fallback of up to two mismatches. Records with no primer match are kept untrimmed as a last-resort BIN representative and tagged accordingly. An optional sub-window crop is available, and other primer sets (`folmer`, `zeale`, `elbrecht_bf2`) are configurable.

Rationale: records come from different assays and cover different, partially overlapping sub-regions. Embedding one consistent window is what keeps the vectors comparable across records; a model vector of a Leray fragment and of a full-length COI of the same species are not guaranteed to coincide. Mismatch tolerance recovers records where a single SNP or sequencing error sits in the primer site: on a 100k Arthropoda sample it cut the unmatched share from 57% to 7% for about 30% more runtime.

References: [ingest/README](../../src/evospaice/ingest/), `filter_bcdm_bin_representatives.py`.
