---
title: Embedding tree validation
description: Tree comparison using Robinson-Foulds distance and tip-to-root-correlation by default
---

## Purpose

Compare an embedding-derived tree with a reference using two metrics, both
enabled by default:

* Robinson-Foulds (RF) distance counts informative clades (rooted) or splits
  (unrooted) present in only one tree, ignoring lengths, support and internal labels.
  Normalized RF divides by their total count across both trees: 0 means matching
  topology on retained taxa; 1 means no informative relationships shared.
  Nonbinary trees are supported, but this validator rejects completely unresolved
  star trees for RF: each tree must retain at least one informative clade or split
  after taxa alignment.
* `tip-to-root-correlation` is Spearman's rho of root-to-tip branch-length sums
  for matching taxa, using average ranks for ties. It measures relative depth,
  not topology or pairwise separation: +1 means the same ordering, -1 the reverse.
  No p-value or biological pass/fail threshold is provided.

The correlation table ranks distances in descending order in both trees:
the largest root-to-tip sum ranks first, with average ranks for ties.
This reporting convention does not change the correlation score or taxon row order.

## Run

Required arguments are `--reference` (reference Newick path), `--inferred`
(inferred Newick path), `--mode` (`rooted` or `unrooted`, controlling RF only)
and `--output-dir` (report directory, created if needed). `--mode` remains required
with `--no-rf`. Optional mapping and taxon-selection arguments are explained in
[Input Rules](#input-rules); reference declarations and JSON metadata are covered
in [Provenance](#provenance).

From the repository root, run this comparison of the mock
[reference](../../../tests/data/reference_tree_mock.nwk) and
[inferred](../../../tests/data/embedding_tree_mock.nwk) fixtures:

Run `uv sync` first on a fresh checkout. This command replaces existing mock
outputs. For your own runs, prefer a new output directory and omit `--overwrite`;
overwriting does not remove stale files for disabled metrics.

```bash
uv run --no-sync evospaice validate \
  --reference tests/data/reference_tree_mock.nwk \
  --inferred tests/data/embedding_tree_mock.nwk \
  --mode unrooted \
  --output-dir results/validation-mock-unrooted \
  --overwrite
```

* `--no-tip-to-root-correlation`: RF only; suitable for trees without lengths
* `--no-rf`: correlation only
* `--rf` and `--tip-to-root-correlation`: explicitly enable the defaults

With `--no-rf`, taxon matching uses labels only: tree cloning, pruning, shared
namespace migration and bipartition encoding are skipped. Mapping validation,
taxon selection and coverage reporting still apply. Correlation measures lengths
on the original trees, including validation of excluded branches.

Progress messages are flushed to stderr with elapsed seconds and stage percentages;
metric results remain on stdout. Percentages mark workflow stages, not elapsed-time
estimates. RF-enabled runs can spend substantial time preparing large trees between
the 30% and 40% updates. Completion is reported only after outputs are written.

Disabling both metrics is an input error. Expected mock results:

| Mode     | Raw RF | Normalized RF | Tip-to-root-correlation |
|----------|--------|---------------|-------------------------|
| Unrooted | 2      | 1             | -0.4                    |
| Rooted   | 4      | 1             | -0.4                    |

## Input Rules

* Each input contains one Newick tree. Tip labels must be unique, nonempty and are case-sensitive.
  Matched labels must represent the same biological identities.
* `--taxon-map` accepts TSV columns `tree`, `label`, `taxon`; tree is `reference`
  or `inferred`. Unlisted labels stay unchanged; many-to-one mappings fail.
* `--taxa-file` selects canonical IDs from a TSV `taxon` column. After selection,
  `--taxa-policy strict` (default) requires equal canonical sets; `intersection`
  retains shared taxa and reports exclusions. Both metrics use the same retained IDs.
* Correlation requires at least three matched tips. RF requires three in rooted
  mode or four in unrooted mode, plus an informative clade or split in each tree.
  Star trees are therefore accepted only with `--no-rf`.
* With correlation enabled, every original non-root edge, including excluded
  branches, needs a finite nonnegative length. Zero is valid; missing, negative,
  NaN or infinite lengths and cumulative overflow are errors. RF-only runs ignore lengths.

For otherwise-valid inputs, constant depths among retained tips in either tree
produce `rho: null`, `status: "undefined"` and an `undefined_reason`.
Both correlation CSVs are still written. Input errors instead exit 2 without
writing new report files; operating-system I/O errors exit 1.

### Roots and Interpretation

RF uses topology-only copies, suppressing unary nodes and artificial unrooted
degree-two roots. Correlation uses lengths from the original supplied roots,
before pruning: the root is zero and its stem is excluded. Inputs are not modified;
no automatic rerooting is performed for correlation. Matching tips or internal
labels does not establish biologically comparable roots.

RF is an exact-match score: resolving a reference polytomy can increase RF without
contradicting it. Correlation uses stored branch lengths, not original embedding
or sequence distances. Positive rescaling preserves ranks, but raw sums in
different units are not equivalent. Correlation requires comparable roots;
unrooted RF does not. Claims of phylogenetic accuracy need an independent reference,
which is itself an estimate.

### Provenance

`--reference-independence` accepts `independent`, `backbone-derived` or `unknown`
(default); this declaration is not verified. `--reference-kind` defaults to
`phylogeny`; choose `taxonomy` for a structural consistency check.
Provide citations and units through a `--metadata` JSON file:

```json
{
  "citation": "reference source",
  "branch_length_units": {
    "reference": "substitutions/site",
    "inferred": "embedding distance"
  }
}
```

Omitted units default to `unknown`. With correlation enabled, supplied units must
be nonempty strings in a `branch_length_units` object; they describe units without
converting or verifying them.

## Outputs

Reports use `schema_version: 5`. Only enabled metrics are printed and included.

| File                          | Contents                                           | Written when        |
|-------------------------------|----------------------------------------------------|---------------------|
| validation.json               | Scores, coverage, provenance, hashes and warnings   | Always              |
| taxa.csv                      | Original labels, canonical IDs and exclusions      | Always              |
| clades.csv                    | Informative clade/split IDs, origins and sizes      | RF enabled          |
| node_lengths.csv              | Root-to-node sums for every original node           | Correlation enabled |
| tip_to_root_correlation.csv    | Retained taxa, paired sums and average ranks        | Correlation enabled |

JSON omits `topology`, `mode` and the RF `root_policy` with `--no-rf`; it omits
`tip_to_root_correlation` and the SciPy version when correlation is disabled.
Branch-length provenance distinguishes RF's ignored lengths from correlation's
used lengths. Node IDs are tree-local preorder indices, not cross-tree identities.
All results are serialized and input/output collisions checked before writing.
See [evaluate.py](evaluate.py) for exact report fields and CSV columns.

## Test

```bash
uv run --no-sync python -m pytest tests/test_validate.py
```

The [validation tests](../../../tests/test_validate.py) cover mock depths and scores,
metric selection, undefined correlation, alignment and invalid inputs.

## References

* [DendroPy tree comparisons](https://jeetsukumaran.github.io/DendroPy/library/treecompare.html)
* [DendroPy phylogenetic distance matrices](https://jeetsukumaran.github.io/DendroPy/library/phylogeneticdistance.html) (background only; not computed by this validator)
* [Diversity background references](../../../docs/README.md#prior-art-relevant-background)
* [Metric implementation](compare.py)
