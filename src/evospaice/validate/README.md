---
title: Embedding tree validation
description: Topology-only tree comparison with Robinson-Foulds distance, precision and recall
---

## Purpose

Compare an embedding-derived tree with a reference using raw and normalized
Robinson-Foulds (RF) distance, precision and recall. All scores use topology only:
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
  --reference tests/data/validation_tree.nwk \
  --inferred tests/data/validation_tree.nwk \
  --mode unrooted \
  --output-dir results/validation-smoke
```

Expected: RF **0**, normalized RF **0**, precision **1**, recall **1**.
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
  --max-tips 100000 \
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

For a mock comparison, replace the inferred path with the included
[mock tree](../../../tests/data/embedding_tree_mock.nwk) and add
`--taxa-policy intersection`. It rearranges four sequence IDs and is not generated
from embeddings. Inspect the retained taxa before interpreting its scores.

`uv run --no-sync python -m evospaice.validate.evaluate` accepts identical arguments.
Use `--help` for all options. Choose `--mode rooted` only when supplied roots
are biologically compatible; otherwise use `--mode unrooted`.

## Metrics

Relationships are rooted clades or unrooted splits. Trivial tips/root and
duplicate unary representations are excluded.

* RF: number of relationships present in only one tree; zero is an exact match
* Normalized RF: RF divided by the total relationship count in both trees; lower is better
* Precision: shared relationships divided by inferred relationships; higher is better
* Recall: shared relationships divided by reference relationships; higher is better

RF uses DendroPy `symmetric_difference`. The report includes the normalization
denominator and shared/inferred-only/reference-only counts. Undefined ratios
are JSON null with reasons, including normalized RF for two unresolved stars.

These are exact-match scores: resolving a reference polytomy can reduce precision
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

* `validation.json`: schema version 2, topology scores, input hashes, DendroPy
  version, provenance, rooting policy, taxon coverage and warnings
* `taxa.csv`: original/canonical identities and retained/excluded status
* `clades.csv`: informative relationship IDs, origin (`both`, `inferred`,
  `reference`) and size; for unrooted trees, size is the canonical split side

`--overwrite` replaces these three reports but does not clean up other files.

Default limit: 5,000 tips per input tree, overridable with `--max-tips`.
Newick inputs (including decompressed `.gz` files) and TSV tables are bounded at
32 MiB. Limits apply before pruning. Raising the tip limit allows larger inputs
but does not guarantee full-tree scalability; parsing, copying and relationship
reporting still consume memory and time. No tip-pair distance matrix is computed.

Exit codes are 0 for report generation, 2 for invalid inputs/configuration,
1 for I/O errors, and 130 for interruption. Successful report generation is not
a scientific pass.

## References

* [DendroPy tree comparisons](https://jeetsukumaran.github.io/DendroPy/library/treecompare.html)
* [DendroPy path distances](https://jeetsukumaran.github.io/DendroPy/library/phylogeneticdistance.html) (background only; not computed by this validator)
* [Diversity background references](../../../docs/README.md#diversity-background)
* [Implementation plan](../../../docs/diversity-tree-validation-plan.md)
