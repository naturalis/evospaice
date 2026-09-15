---
title: Embedding tree validation
description: Topology-only tree comparison with raw and normalized Robinson-Foulds distance
---

## Purpose

Compare an embedding-derived tree with a reference using raw and normalized
Robinson-Foulds (RF) distance. Both scores use topology only:
branch lengths, support values and internal node labels are ignored.

Both trees must represent the same biological tip identities. A taxonomy backbone
used during construction measures structural consistency, not independent
phylogenetic accuracy.

## Quick Test

From the repository root, use the existing development environment:

```bash
uv run --no-sync python -m pytest tests/test_validate.py
```

For a fresh checkout, install dependencies with `uv sync` first. `--no-sync`
uses the installed environment without resolving unrelated optional packages.

To try the command, compare the small included tree with itself:

```bash
uv run --no-sync evospaice validate \
  --reference tests/data/reference_tree.nwk \
  --inferred tests/data/reference_tree.nwk \
  --mode unrooted \
  --output-dir results/validation-smoke
```

Expected: RF **0**, normalized RF **0**.
This checks the software, not biological accuracy.

Use a new output directory for each comparison; repeating a command against a
nonempty directory requires `--overwrite`. Outputs cannot overwrite input files.

## Compare Your Tree

Once `data/embedding_tree.nwk` exists with the same unique tip identities as the
reference, run:

```bash
uv run --no-sync evospaice validate \
  --reference data/pruned.tre.txt \
  --inferred data/embedding_tree.nwk \
  --mode unrooted \
  --output-dir results/validation-embeddings
```

> [!IMPORTANT]
> The existing reference uses sequence-record IDs, not BIN IDs. A BIN-labelled
> embedding tree needs a documented correspondence to reference tips. If several
> reference records belong to one BIN, select one representative per BIN or apply
> a scientifically justified aggregation before comparison. A many-to-one rename
> is rejected. Intersection alone cannot match sequence IDs to BIN IDs.

For intentionally different coverage, add `--taxa-policy intersection` after
aligning identities. Start with a benchmark clade rather than interpreting a
small retained fraction as evidence for the full tree.

`uv run --no-sync python -m evospaice.validate.evaluate` accepts identical arguments.
Use `--help` for all options. Choose `--mode rooted` only when supplied roots
are biologically compatible; otherwise use `--mode unrooted`.

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

## Outputs and Limits

Scores are printed to the terminal. Each run writes three files:

* `validation.json`: schema version 4, RF scores, input hashes, DendroPy
  version, provenance, rooting policy, taxon coverage and warnings
* `taxa.csv`: original/canonical identities and retained/excluded status
* `clades.csv`: informative relationship IDs, origin (`both`, `inferred`,
  `reference`) and size; for unrooted trees, size is the canonical split side

`--overwrite` replaces these three reports but does not clean up other files.

Schema version 4 removes the tip-limit metadata. Version 3 removed precision,
recall and their undefined-value reasons from the topology object; RF scores
and supporting relationship counts remain.

There is no configured maximum number of tips per input tree.
Newick inputs (including decompressed `.gz` files) and TSV tables are bounded at
32 MiB. Byte limits apply before pruning. Removing the tip cap does not
guarantee full-tree scalability; parsing, copying and relationship
reporting still consume memory and time. No tip-pair distance matrix is computed.

Exit codes are 0 for report generation, 2 for invalid inputs/configuration,
1 for I/O errors, and 130 for interruption. Successful report generation is not
a scientific pass.

## References

* [DendroPy tree comparisons](https://jeetsukumaran.github.io/DendroPy/library/treecompare.html)
* [DendroPy path distances](https://jeetsukumaran.github.io/DendroPy/library/phylogeneticdistance.html) (background only; not computed by this validator)
* [Diversity background references](../../../docs/README.md#diversity-background)
* [Implementation plan](../../../docs/diversity-tree-validation-plan.md)
