---
title: Embedding tree validation
description: Topology-only tree comparison with raw and normalized Robinson-Foulds distance
---

## Purpose

Compare an embedding-derived tree with a reference using raw and normalized
Robinson-Foulds (RF) distance. Both scores use topology only:
branch lengths, support values and internal node labels are ignored.

Both trees must represent the same biological tip identities.

## Quick Test

From the repository root, use the existing development environment:

```bash
uv run --no-sync python -m pytest tests/test_validate.py
```

For a fresh checkout, install dependencies with `uv sync` first. `--no-sync`
uses the installed environment without resolving unrelated optional packages.

## Mock Comparison

The included [reference tree](../../../tests/data/reference_tree.nwk) and
[mock tree](../../../tests/data/embedding_tree_mock.nwk) share tip labels A, B,
C and D. The mock rearranges their groupings; it is not generated from embeddings.

```bash
uv run --no-sync evospaice validate \
  --reference tests/data/reference_tree.nwk \
  --inferred tests/data/embedding_tree_mock.nwk \
  --mode unrooted \
  --output-dir results/validation-mock-unrooted
```

Use a new output directory for each comparison; repeating a command against a
nonempty directory requires `--overwrite`. Outputs cannot overwrite input files.

To compare the same fixtures as rooted trees, use `--mode rooted` and a separate
output directory such as `results/validation-mock-rooted`.

Ignoring branch lengths and internal node labels, the topologies are:

```text
Reference: ((A,B),(C,D));
Mock:      ((C,B),(D,A));
```

### Unrooted Calculation

1. Suppress the artificial degree-two root and exclude terminal-edge splits.
2. Extract the nontrivial split in each tree: `AB | CD` in the reference and
  `BC | AD` in the mock. A split and its reverse count as one relationship.
3. Count relationships present in only one tree: one reference-only split plus
  one inferred-only split gives RF = **2**.
4. Divide by the total number of observed relationships: 2 / (1 + 1) = **1**.

### Rooted Calculation

1. Treat Z as the supplied root in both fixtures.
2. Extract nontrivial descendant clades, excluding tips and the full root clade:
  `{A,B}` and `{C,D}` in the reference; `{B,C}` and `{A,D}` in the mock.
3. No clades are shared, so RF = 2 + 2 = **4**.
4. Normalize by the total clade count: 4 / (2 + 2) = **1**.

| Mode     | Raw RF | RF denominator | Normalized RF | Shared relationships |
|----------|--------|----------------|---------------|----------------------|
| Unrooted | 2      | 2              | 1             | 0                    |
| Rooted   | 4      | 4              | 1             | 0                    |

Normalized RF of 1 means no informative relationships are shared. It does not
mean every aspect of the trees differs. Naming the root Z does not establish
that the supplied roots are biologically comparable.

## Metrics

Relationships are rooted clades or unrooted splits. Trivial tips/root and
duplicate unary representations are excluded.

* RF: number of relationships present in only one tree; zero is an exact match
* Normalized RF: RF divided by the total relationship count in both trees; lower is better

For relationship sets $S_{\mathrm{ref}}$ and $S_{\mathrm{inf}}$:

$$
RF = |S_{\mathrm{ref}} \setminus S_{\mathrm{inf}}|
  + |S_{\mathrm{inf}} \setminus S_{\mathrm{ref}}|
$$

$$
RF_{\mathrm{normalized}} =
\frac{RF}{|S_{\mathrm{ref}}| + |S_{\mathrm{inf}}|}
$$

RF uses DendroPy `symmetric_difference`. The report includes the normalization
denominator and shared/inferred-only/reference-only counts. Normalized RF is
JSON null with a reason when both trees have no resolved relationships.

These are exact-match scores: resolving a reference polytomy can increase RF
without contradicting the reference. No support filtering or compatibility
classification is performed. The sequence-derived reference is itself an estimate.

## Comparison Policies

* Exact unique leaf labels are required. `--taxon-map` accepts TSV columns
  `tree`, `label`, `taxon`, where tree is `inferred` or `reference`. Unlisted
  labels retain their identity. Many-to-one mappings fail.
* `--taxa-policy strict` is the default and requires equal canonical sets.
  Explicit `intersection` prunes copies and reports exclusions. `--taxa-file`
  accepts a TSV with a `taxon` column selecting a benchmark set.
* `--reference-kind taxonomy` labels a structural consistency check. Set
  `--reference-independence independent|backbone-derived|unknown` and provide
  citations and construction provenance in a `--metadata` JSON object.
  Independence is declared, not automatically verified. Holding out a clade
  requires withholding its constraints before construction, not pruning afterward.
* Unary nodes and artificial unrooted degree-two roots are suppressed. Input
  files are not modified. Branch lengths are discarded from working copies.


## References

* [DendroPy tree comparisons](https://jeetsukumaran.github.io/DendroPy/library/treecompare.html)
* [DendroPy path distances](https://jeetsukumaran.github.io/DendroPy/library/phylogeneticdistance.html) (background only; not computed by this validator)
* [Diversity background references](../../../docs/README.md#diversity-background)
* [Implementation plan](../../../docs/diversity-tree-validation-plan.md)
