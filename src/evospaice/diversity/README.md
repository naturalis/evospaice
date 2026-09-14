# Phylogenetic diversity

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
