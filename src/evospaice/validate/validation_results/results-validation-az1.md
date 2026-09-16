---
title: Correlation-only validation results
description: Results and interpretation of the validation-az1 tree comparison
---

## Run info:
uv run --no-sync evospaice validate \
  --reference data/pruned.tre.txt \
  --inferred data/unsupervised_nj_tree.tre.txt \
  --mode unrooted \
  --taxa-policy intersection \
  --rf \
  --no-tip-to-root-correlation \
  --output-dir results/validation-az1


## Summary

The comparison completed successfully with Spearman's rho of
**-0.004153686900401179** across **61,600 matched tips**. This is effectively
zero rank correlation: tips with larger supplied-root distances in the reference
tree do not consistently have larger or smaller distances in the inferred tree.
The tiny negative sign does not indicate a meaningful inverse relationship.

This run provides no evidence of appreciable agreement in root-to-tip depth
ordering on the shared taxa. It does not test topology, pairwise evolutionary
distances, beta diversity, or the overall usefulness of embeddings.

## Command

Run from the repository root:

```bash
uv run --no-sync evospaice validate \
  --reference data/pruned.tre.txt \
  --inferred data/unsupervised_nj_tree.tre.txt \
  --mode unrooted \
  --taxa-policy intersection \
  --no-rf \
  --output-dir results/validation-az1 \
  --overwrite
```

## Measurements

| Measurement | Result |
|-------------|--------|
| Spearman's rho | -0.004153686900401179 |
| Correlation status | `ok` (defined and computed successfully, not a biological pass) |
| Matched tips | 61,600 |
| Inferred tips: original / retained / excluded | 181,078 / 61,600 / 119,478 |
| Reference tips: original / retained / excluded | 91,376 / 61,600 / 29,776 |
| Excluded tip records across both trees | 149,254 |
| Original inferred nodes measured | 185,076 |
| Original reference nodes measured | 182,751 |
| RF topology comparison | Disabled |
| Total runtime | 16.1 seconds in the supplied terminal log |
| Taxon matching time | Approximately 1.0 second (8.2s to 9.2s in the log) |
| Libraries | DendroPy 5.0.13; SciPy 1.17.1 |

Scores, coverage and library versions come from the saved
[validation report](../../../results/validation-az1/validation.json).
Timing and node counts come from the supplied terminal log. Runtime is an
observation for this run, not a general performance guarantee.

## Interpretation Limits

* Correlation uses original supplied roots, before pruning. The root contributes
  zero and its stem is excluded. `--mode unrooted` controls RF only; it does not
  make this correlation root-independent or reroot either tree.
* Comparable biological roots have not been established. Different rooting
  choices can change depth ordering and therefore the score.
* Branch-length units are recorded as `unknown` for both trees. Positive uniform
  rescaling would not change Spearman ranks, but comparable biological meaning
  of the lengths is not established by this run.
* The reference is declared as a phylogeny, but its independence is `unknown`.
* No p-value, uncertainty interval or biological pass/fail threshold was computed.
  Near-zero correlation does not prove statistical independence.
* Results apply to the shared labels only; matching labels is assumed to identify
  the same biological entities. This command does not select the Papilio genus.

Before drawing biological conclusions, verify root comparability, label identity
and branch-length meaning. Topology or beta-diversity claims require separate
evaluations; this score alone cannot establish them.

## Output Files

The output directory is `results/validation-az1/`, relative to the repository
root (`/workspaces/ai-sequence-identification`). It contains four files:

| File | Contents |
|------|----------|
| [validation.json](../../../results/validation-az1/validation.json) | Score, coverage, warnings, versions and input SHA-256 hashes |
| [taxa.csv](../../../results/validation-az1/taxa.csv) | Original and canonical labels, retention flags and exclusion reasons |
| [node_lengths.csv](../../../results/validation-az1/node_lengths.csv) | Supplied-root length sums for every original node in both trees |
| [tip_to_root_correlation.csv](../../../results/validation-az1/tip_to_root_correlation.csv) | Matched taxa, paired length sums and descending ranks with averaged ties |

No `clades.csv` was generated because RF was disabled. Reusing this command with
`--overwrite` replaces these reports, so they are not an immutable run archive.
See [metric documentation](README_metrics.md) for calculation and input rules.