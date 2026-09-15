---
title: Phylogenetic diversity
description: Library-backed Faith PD and UniFrac evaluation for sample communities
---

## Metrics

This package measures biodiversity after sample taxa have been placed on a
rooted, branch-length-scaled reference tree.

- **Alpha diversity:** rooted Faith's phylogenetic diversity (PD), the sum of
  branches connecting all observed taxa in one sample to the root.
- **Beta diversity:** unweighted UniFrac for presence/absence and normalized
  weighted UniFrac for relative abundance.

The evaluator accepts a Newick tree and a CSV or TSV table with exactly these
columns:

```text
sample	taxon	abundance
sample_1	A	10
sample_1	B	4
sample_2	D	7
```

Taxon values must exactly match unique leaf labels in the tree. Abundances must
be finite and non-negative.

Run the known-answer fixture:

```bash
uv run python -m evospaice.diversity.evaluate \
  --tree tests/data/diversity_tree.nwk \
  --samples tests/data/diversity_samples.tsv \
  --output-dir results/diversity
```

This writes:

- `alpha_diversity.csv`: one Faith's PD value per sample.
- `beta_diversity.csv`: one row per sample pair, with unweighted and weighted
  UniFrac distances.

The equivalent top-level command is `uv run evospaice diversity` with the same
arguments. A `manifest.json` records input SHA-256 values, package versions,
backend, root convention and weighted normalization. Existing CSV schemas and
the scalar Python functions remain supported.

## Backends

The default `--backend skbio` uses scikit-bio for all three metrics, preparing
the tree and sample matrix once per batch. Weighted UniFrac explicitly uses
`normalized=True`. The root in the supplied Newick is the study root; this
command does not discover or validate a biological root. Its incoming stem
is excluded, while paths below it are retained. Rooted polytomies are supported.

The optional `--backend unifrac` uses native fp64 unweighted and normalized
weighted UniFrac with an in-memory BIOM table. PD still uses scikit-bio. Tip
bypass, variance adjustment and rarefaction are disabled. A missing native
backend is an error, not a silent fallback.

UniFrac 1.5 on PyPI expects native libssu headers and a populated `CONDA_PREFIX`;
`uv sync --extra fast-diversity` alone is not sufficient in a plain container.
The verified installation route is a separate Conda/Mamba environment:

```bash
micromamba create -y -p /tmp/evospaice-native/env \
  -c conda-forge -c bioconda python=3.12 unifrac dendropy pytest
PYTHONPATH=src UNIFRAC_USE_GPU=N OMP_NUM_THREADS=2 \
  /tmp/evospaice-native/env/bin/python -m evospaice.diversity.evaluate \
  --tree tests/data/diversity_tree.nwk \
  --samples tests/data/diversity_samples.tsv \
  --backend unifrac --output-dir results/diversity-native
```

The environment path is disposable; select a persistent location for ongoing
use. UniFrac 1.5.1, scikit-bio 0.7.3 and DendroPy 5.1.0 were tested together
on Python 3.12. CPU thread count is controlled through `OMP_NUM_THREADS`.
The project extra declares Python dependencies for installations that already
provide the required native libraries.

## Input and Resource Policies

* Abundances below one remain present. PD and unweighted UniFrac receive explicit
  presence/absence arrays. The installed scikit-bio 0.7.3 node accumulator casts
  weighted counts to integers, so its adapter converts decimal values to exact
  proportional integers per sample. Ratios exceeding the exact integer range
  raise an error recommending the native floating-point backend; no rounding is
  performed silently.
* All non-root lengths must be finite and non-negative. Missing lengths are not
  replaced with zeros. Zero-length edges are allowed, but zero-denominator
  UniFrac comparisons are errors.
* Empty samples have PD zero. Weighted UniFrac requires positive finite totals.
  Unweighted UniFrac permits one empty sample when the union spans a positive
  length, but rejects a zero-length union. A one-sample batch writes only alpha
  results and beta headers.
* Labels are matched exactly, including case, underscores and quoted colons.
  Unknown taxa are errors even when their abundance is zero. Read abundance is
  a proxy, not an unbiased organism-abundance measurement.
* `--memory-mb` defaults to 512 and guards estimated batch arrays. It is not a
  process-wide memory guarantee. Large sample matrices and result tables still
  grow with the input and number of sample pairs; use bounded benchmark subsets.

## References

* [Scikit-bio diversity](https://scikit.bio/docs/latest/diversity.html)
* [Weighted UniFrac normalization](https://scikit.bio/docs/latest/generated/skbio.diversity.beta.weighted_unifrac.html)
* [Optimized UniFrac installation and methods](https://github.com/biocore/unifrac)
