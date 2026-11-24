---
title: Taxonomy-only baseline against the Bactria reference
description: RF comparison of a tree built from the BOLD taxonomy alone with the Lepidoptera reference, to put the embedding-tree RF values in context
ms.date: 2026-11-09
---

## Purpose

The taxonomy-constrained embedding tree (see
[aml-pipeline-validation-taxonomic.md](aml-pipeline-validation-taxonomic.md))
inherits much of its structure from the Linnaean classification, and so does the
reference tree. Its normalised RF distance (0.794) can only be interpreted next to
a tree that carries the taxonomy and nothing else.

## Inputs and commands

* Tips: the 61,380 reference tips with a species in
  [pruned.taxonomy.tsv](../../../../data/pruned.taxonomy.tsv)
* Taxonomy: genus, tribe, subfamily and family of each species, read from the
  BOLD scaffold [BOLD_Public.30-Jun-2026.tre.gz](../../../../data/BOLD_Public.30-Jun-2026.tre.gz)
* Reference: [pruned.tre.txt](../../../../data/pruned.tre.txt)
  (SHA-256 `a23fcd828d1fe8db49be0434fb9d27f02e43c7afc28050e52f16d13bbac8cada`)

```bash
PYTHONPATH=src python3 -m evospaice.validate.taxonomy_baseline \
    --taxonomy data/pruned.taxonomy.tsv \
    --scaffold data/BOLD_Public.30-Jun-2026.tre.gz \
    --reference data/pruned.tre.txt \
    --out results/taxonomy_baseline/taxonomy_baseline.tre

PYTHONPATH=src python3 -m evospaice.validate.evaluate \
    --inferred results/taxonomy_baseline/taxonomy_baseline.tre \
    --reference data/pruned.tre.txt \
    --mode unrooted --taxa-policy intersection --rf --no-tip-to-root-correlation \
    --output-dir results/taxonomy_baseline/eval --overwrite
```

Run locally with DendroPy 5.1.3 in 4 min 45 s. Baseline tree SHA-256:
`e946f9f784f4e0b11968e4260d62c80c8a715af9d5f67b53eadf15653d264bff`.

## Results

| Tree | Shared tips | Informative splits (tree / reference) | Shared | Recovered (of reference) | Precision (of tree) | nRF |
|---|---:|---:|---:|---:|---:|---:|
| Taxonomy-only baseline | 61,380 | 14,043 / 61,377 | 6,844 | 11.2% | 48.7% | 0.819 |
| Taxonomy-constrained NJ (AZ2) | 61,381 | 56,718 / 61,378 | 12,146 | 19.8% | 21.4% | 0.794 |
| Unconstrained k-means + NJ | 61,600 | 3,975 / 61,597 | 2 | <0.01% | 0.05% | 1.000 |

## Interpretation

The embeddings add correct resolution beyond the taxonomy (recovered reference
splits rise from 11.2% to 19.8%), but most of the splits they add are absent from
the reference (precision drops from 48.7% to 21.4%). About half of the
taxonomy's own splits are not in the reference either: many BOLD taxa are not
monophyletic on the COI-based reference. The reference is not independent of the
taxonomy or of COI, so none of these numbers measure accuracy against the true
phylogeny.
