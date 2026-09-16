---
title: Numbered tree-pair validation results
description: Unrooted RF and tip-to-root correlation results and descriptive statistics for ten matching numbered tree pairs
---

## Summary

All **10 of 10 comparisons completed successfully** on 2026-09-16, pairing
`tests/data/reference_NN.nwk` with `tests/data/infered_NN.nwk` for `NN` from
`01` through `10`. The input filenames use the spelling `infered`.
Each run used unrooted RF, tip-to-root correlation and strict taxon matching,
with no mapping or taxon selection.

Every pair retained all 10 tips, with no exclusions. The batch covers 100
distinct taxon labels, with no overlap between pairs. All ten correlations
have status `ok`, meaning they were defined and computed, not that a biological
quality threshold was passed.

Mean normalized RF was **0.773260**, indicating substantial exact-split
disagreement in this batch. Mean Spearman rho was **0.092700**, with values
spanning negative and positive depth-order associations. These metrics assess
different properties and do not provide a combined accuracy score.

## Pairwise Comparison

Ref. and inf. splits are informative unrooted split counts. Shared counts
splits present in both trees. Lower RF indicates closer topology; higher rho
indicates more similar ordering of supplied-root tip depths. Decimal scores
are rounded to six places; linked JSON reports retain full precision.

| Pair | Tips | Ref. splits | Inf. splits | Shared | RF | Normalized RF | Spearman rho |
|------|------|-------------|-------------|--------|----|---------------|--------------|
| 01   | 10   | 7           | 6           | 2      | 9  | 0.692308      | 0.498483     |
| 02   | 10   | 7           | 6           | 1      | 11 | 0.846154      | 0.430303     |
| 03   | 10   | 7           | 7           | 2      | 10 | 0.714286      | 0.060791     |
| 04   | 10   | 7           | 5           | 2      | 8  | 0.666667      | -0.490909    |
| 05   | 10   | 7           | 6           | 4      | 5  | 0.384615      | -0.640256    |
| 06   | 10   | 7           | 6           | 0      | 13 | 1.000000      | -0.303953    |
| 07   | 10   | 7           | 7           | 0      | 14 | 1.000000      | -0.054545    |
| 08   | 10   | 7           | 7           | 1      | 12 | 0.857143      | 0.267478     |
| 09   | 10   | 7           | 7           | 3      | 8  | 0.571429      | 0.668696     |
| 10   | 10   | 7           | 7           | 0      | 14 | 1.000000      | 0.490909     |

RF equals reference-only plus inferred-only splits, or equivalently the total
split count minus twice the shared count. Normalized RF divides RF by the sum
of reference and inferred split counts. Denominators range from 12 to 14 here
because inferred trees differ in resolution.

## Descriptive Statistics

Statistics use all ten full-precision report values with equal weight per pair.
Sample SD uses a denominator of nine (`n - 1`); it describes between-pair
variation, not uncertainty in the mean. The mean rho is an arithmetic summary
of ten separate correlations, not a pooled correlation across all 100 tips.

| Metric              | Mean      | Median    | Sample SD | Minimum   | Maximum   |
|---------------------|-----------|-----------|-----------|-----------|-----------|
| Retained tips       | 10.000000 | 10.000000 | 0.000000  | 10.000000 | 10.000000 |
| Raw RF              | 10.400000 | 10.500000 | 2.951459  | 5.000000  | 14.000000 |
| Normalized RF       | 0.773260  | 0.780220  | 0.205415  | 0.384615  | 1.000000  |
| Spearman rho        | 0.092700  | 0.164134  | 0.454286  | -0.640256 | 0.668696  |
| Shared splits       | 1.500000  | 1.500000  | 1.354006  | 0.000000  | 4.000000  |

* Pair 05 has the lowest normalized RF (0.384615), sharing four splits, but
  also the most negative rho (-0.640256).
* Pair 09 has the highest rho (0.668696); its normalized RF is 0.571429.
* Pairs 06, 07 and 10 share no informative splits with their respective
  references, giving normalized RF of 1. None of the ten pairs has RF of 0.
* Six correlations are positive and four are negative; none is undefined.

## Interpretation Limits

* RF tests exact split agreement and ignores lengths. Different resolution
  affects its denominator; resolving a polytomy can increase RF without
  contradicting the reference. RF is not a percentage of biological accuracy.
* Correlation measures original supplied-root branch-length sums, excluding
  the root stem. Unrooted mode applies only to RF; it does not reroot the trees
  or make correlation root-independent. Comparable biological roots are unverified.
* Branch-length units are `unknown` for both trees in every pair. Rho compares
  ranks, not absolute lengths, pairwise evolutionary separation or beta diversity.
* Reference kind defaults to `phylogeny`, and reference independence is
  `unknown`. These declarations do not verify the source or independence of
  the input trees.
* Each pair contains only ten tips and uses a different taxon set. These are
  descriptive comparisons, not repeated measurements of the same tree or
  evidence of general performance. No p-values, confidence intervals or
  biological pass/fail thresholds were computed.

## Reproduce

Run from the repository root with the project environment installed. On a fresh
checkout, run `uv sync` first. This batch used DendroPy 5.0.13 and SciPy 1.17.1;
`--no-sync` leaves the existing dependency environment unchanged.

```bash
for index in {01..10}; do
  uv run --no-sync evospaice validate \
    --reference "tests/data/reference_${index}.nwk" \
    --inferred "tests/data/infered_${index}.nwk" \
    --mode unrooted \
    --output-dir "results/validation-numbered-unrooted/pair-${index}" \
    --overwrite
done
```

> [!WARNING]
> `--overwrite` replaces reports in each pair directory. To preserve this batch,
> choose a new output directory and omit the flag. Overwriting does not remove
> stale files for disabled metrics.

## Saved Reports

Each pair directory contains five files: a JSON report with scores, provenance
and input SHA-256 hashes, plus CSVs for taxa, splits, original-node depths and
paired tip depths with ranks. All ten reports, input hashes and CSV row counts
were checked against the inputs and recorded coverage.

* [Pair 01 report](../../../../results/validation-numbered-unrooted/pair-01/validation.json)
* [Pair 02 report](../../../../results/validation-numbered-unrooted/pair-02/validation.json)
* [Pair 03 report](../../../../results/validation-numbered-unrooted/pair-03/validation.json)
* [Pair 04 report](../../../../results/validation-numbered-unrooted/pair-04/validation.json)
* [Pair 05 report](../../../../results/validation-numbered-unrooted/pair-05/validation.json)
* [Pair 06 report](../../../../results/validation-numbered-unrooted/pair-06/validation.json)
* [Pair 07 report](../../../../results/validation-numbered-unrooted/pair-07/validation.json)
* [Pair 08 report](../../../../results/validation-numbered-unrooted/pair-08/validation.json)
* [Pair 09 report](../../../../results/validation-numbered-unrooted/pair-09/validation.json)
* [Pair 10 report](../../../../results/validation-numbered-unrooted/pair-10/validation.json)

See the [metric documentation](../README_metrics.md) for calculation rules and
output column definitions.
