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

## Run With the Existing Reference and a Mock Tree

From the repository root:

```bash
uv run evospaice validate \
  --reference data/pruned.tre \
  --inferred tests/data/embedding_tree_mock.nwk \
  --mode unrooted \
  --taxa-policy intersection \
  --max-tips 100000 \
  --output-dir results/validation-mock
```

The reference currently contains 91,376 sequence-record tips. The
[mock tree](../../../tests/data/embedding_tree_mock.nwk) deliberately rearranges
four of those labels: `AANIC006-10`, `AANIC018-10`, `AANIC027-10` and `AANIC030-10`.
It is not generated from embeddings. Intersection mode prunes copies to those
four shared tips and records all exclusions. Expected: RF **2**, normalized RF
**1**, precision **0**, recall **0**. This is a software smoke test, not a
biological validation result.

Use a new output directory for each comparison; repeating a command against a
nonempty directory requires `--overwrite`.

## Compare a Future Embedding Tree

Once `data/embedding_tree.nwk` exists with the same unique tip identities as the
reference, run:

```bash
uv run evospaice validate \
  --reference data/pruned.tre \
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

`uv run python -m evospaice.validate.evaluate` accepts identical arguments.
Use `--help` for all options. Choose `--mode rooted` only when supplied roots
are biologically compatible; otherwise use `--mode unrooted`.

## Metrics

Let $I$ be the set of informative relationships in the inferred tree, $R$ the
corresponding reference set, and $S = |I \cap R|$. Relationships are rooted clades
or unrooted splits; trivial tips/root and duplicate unary representations are
excluded.

* Raw RF: $|I \setminus R| + |R \setminus I|$. Zero means identical relationship sets.
* Normalized RF: $\mathrm{RF} / (|I| + |R|)$. Lower is better; one means no shared informative relationships when the denominator is positive.
* Precision: $S / |I|$. The fraction of inferred relationships recovered in the reference.
* Recall: $S / |R|$. The fraction of reference relationships recovered in the inferred tree.

RF uses DendroPy `symmetric_difference`. The report includes the normalization
denominator and shared/inferred-only/reference-only counts. Undefined ratios
are JSON null with reasons, including normalized RF for two unresolved stars.

These are exact-match scores: resolving a reference polytomy can reduce precision
without contradicting the reference. No support filtering or compatibility
classification is performed. The sequence-derived reference is itself an estimate.

For an identity check, use `tests/data/diversity_tree.nwk` as both `--reference`
and `--inferred`. Expected: RF and normalized RF zero, precision and recall one.

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

The former branch-length, distance, embedding, replicate, support-filtering,
baseline and diversity options and report sections have been removed. The
standalone diversity package is unchanged. Use a fresh directory when migrating
from older reports; `--overwrite` does not clean up old optional CSV files.

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
* [Diversity backend documentation](../diversity/README.md)
* [Implementation plan](../../../docs/diversity-tree-validation-plan.md)
