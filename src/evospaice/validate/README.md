---
title: Embedding tree validation
description: Tree comparison using Robinson-Foulds distance and tip-to-root-correlation by default
---

## Purpose

Compare an embedding-derived tree with a reference using raw and normalized
Robinson-Foulds (RF) distance. Both scores use topology only:
branch lengths, support values and internal node labels are ignored.

Also compute `tip-to-root-correlation`, Spearman's rho of cumulative
branch lengths from each original supplied root to the retained species tips.
This experimental score measures relative depth, not topological accuracy or
pairwise tip separation. It complements RF and does not replace it.

Both metrics are computed by default. Use `--no-tip-to-root-correlation` for
RF only, or `--no-rf` for correlation only. Disabling both is an input error.
The positive flags `--rf` and `--tip-to-root-correlation` explicitly enable
their respective metrics but are unnecessary for the default run.

By default, inputs need finite, nonnegative lengths on every non-root edge.
For topology-only Newick inputs without lengths, select RF only explicitly.

Both trees must represent the same biological tip identities. Both the trees in tests/data are mock.

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
C and D. 

This command computes both RF and tip-to-root-correlation:

```bash
uv run --no-sync evospaice validate \
  --reference tests/data/reference_tree.nwk \
  --inferred tests/data/embedding_tree_mock.nwk \
  --mode unrooted \
  --output-dir results/validation-mock-unrooted
  --overwrite
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

### Tip-to-Root Calculation

The same default command uses the following original root-to-tip sums and ranks:

| Taxon | Reference sum | Inferred sum | Reference rank | Inferred rank |
|-------|---------------|--------------|----------------|---------------|
| A     | 0.07          | 0.35         | 1              | 4             |
| B     | 0.08          | 0.08         | 2              | 2             |
| C     | 0.32          | 0.07         | 3              | 1             |
| D     | 0.35          | 0.32         | 4              | 3             |

The mock `tip-to-root-correlation` is **-0.4**. RF remains 2 in unrooted
mode and 4 in rooted mode, with normalized RF of 1 in either mode.

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
denominator and shared/inferred-only/reference-only counts. When RF is enabled,
each tree must retain
at least one informative rooted clade or unrooted split after taxa alignment and
pruning. If either tree has none, validation reports an input error identifying
the tree and exits with code 2 without writing a report. For example, a star tree
`(A,B,C,D);` is rejected in either mode.

For valid inputs, normalized RF is always numeric.

These are exact-match scores: resolving a reference polytomy can increase RF
without contradicting the reference. No support filtering or compatibility
classification is performed. The sequence-derived reference is itself an estimate.

### Tip-to-Root-Correlation

For every original node $v$, compute the sum along the supplied root-to-node path:

$$
L(v) = \sum_{e \in \operatorname{path}(\mathrm{root},v)} \ell(e)
$$

The root has value zero. Its own stem length is ignored, even if present in the
Newick input. For the canonical tip identities $T$ retained by taxon alignment:

$$
\rho = \operatorname{Spearman}
\left((L_{\mathrm{reference}}(t))_{t\in T},
  (L_{\mathrm{inferred}}(t))_{t\in T}\right)
$$

Both vectors must contain exactly the retained canonical IDs, each once, and
are aligned by sorted ID. SciPy computes the correlation and average ranks for
ties. No p-value is reported. Positive rescaling of one tree preserves the score.
Higher is better for agreement in relative depth: +1 means the same ordering,
0 means no rank correlation, and -1 means reversed ordering. Different topologies
can have equal root-to-tip values, so this is not a topology score.

At least three matched tips are required. When RF is enabled, it requires at least
three in rooted mode or four in unrooted mode and an informative relationship in
each tree. With `--no-rf`, those topology requirements do not apply; a star tree
with at least three tips and valid lengths can be compared.
If either depth vector is constant (including ultrametric trees), rho is undefined.
Otherwise-valid inputs produce a successful report with `rho: null`,
`status: "undefined"`, and an `undefined_reason` identifying the constant tree or
trees. Both correlation CSVs are still written. This is not an input error.

Missing, negative, NaN or infinite non-root lengths, and non-finite cumulative
sums, are input errors unless `--no-tip-to-root-correlation` is specified.
Zero is accepted; lengths
are never clipped or imputed. Every original non-root edge is checked, including
excluded branches. Invalid lengths identify the tree and node and cause exit 2
before new report files are written. RF-only runs retain their length-tolerant
behavior.

The iterative traversal takes O(V) time and storage for V original nodes, followed
by O(T log T) ranking for T retained tips. No pairwise distance matrix is built.

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
* RF suppresses unary nodes and artificial unrooted degree-two roots. Input
  files and original trees are not modified. Branch lengths are discarded only
  from RF working copies; original trees preserve lengths for tip-to-root-correlation.
* Tip-to-root-correlation uses original supplied roots before pruning or suppression.
  `--mode` controls RF alone. No automatic rerooting or root-acknowledgement flag
  is used. Matching tip identities or internal labels does not establish comparable
  biological roots; internal nodes are never matched across trees.
  `--mode` remains a required CLI argument but has no effect on correlation-only
  scores and is omitted from correlation-only reports.
* Lengths are stored tree-edge lengths, not original embedding vectors or sequence
  distances. Fitted tree paths need not reproduce the original pairwise distances.
  Raw sums from trees with different units must not be treated as equivalent.
  Root provenance and an independent reference remain prerequisites for
  interpretation. No biological pass/fail threshold is defined for this metric.

### Branch-Length Units

Record units in the existing `--metadata` JSON file, for example:

```json
{
  "citation": "reference source",
  "branch_length_units": {
    "reference": "substitutions/site",
    "inferred": "embedding distance"
  }
}
```

Each omitted per-tree unit defaults to `unknown` in the metric's provenance.
When enabled, `branch_length_units` must be an object and supplied per-tree values
must be nonempty strings. Units are descriptive provenance, not a conversion or
verification of comparability. No additional CLI flags are needed.

## Output Schema

All new runs use `schema_version: 5`. Default runs print RF and the
`tip-to-root-correlation` score, or its undefined reason. Explicit RF-only runs
retain the RF-only terminal output; correlation-only runs print only that score.

* `validation.json`: existing topology, coverage, mode, RF root policy, metadata,
  warnings, input hashes and DendroPy version
* `taxa.csv`: original labels, canonical IDs, retention and exclusion reasons
* `clades.csv`: informative clade or split identifiers, origins and sizes, unless
  `--no-rf` is specified

Reports include `tip_to_root_correlation` unless explicitly disabled, with
`rho`, `compared_tip_count`, `status`, `root_policy`, `branch_lengths`,
`branch_length_units` and `node_id_policy`. `undefined_reason` appears only for an
undefined score. The metric's root policy is
`original_supplied_root_stem_excluded`; its lengths are `stored_non_root_edges`.
`versions.scipy` is recorded only for enabled runs.

RF-only reports keep `branch_lengths: "ignored"`. Default reports use
`branch_lengths: {"rf": "ignored", "tip_to_root_correlation": "used"}`
to distinguish the two calculations. Existing topology fields are preserved.
With `--no-rf`, `topology`, the RF `mode` and top-level RF `root_policy` are
omitted, and `branch_lengths` contains only `tip_to_root_correlation: "used"`.

Default runs also write these files, even when rho is undefined. They are omitted
only with `--no-tip-to-root-correlation`:

* `node_lengths.csv`: `tree`, `node_id`, `parent_id`, `original_label`, `node_kind`,
  `root_to_node_sum`, covering every original node, including excluded tips
* `tip_to_root_correlation.csv`: `taxon`, `reference_sum`, `inferred_sum`,
  `reference_rank`, `inferred_rank`, covering retained canonical tips only

Node IDs are zero-based preorder indices local to each input serialization, not
cross-tree identities. The root's parent ID is empty; node kinds are `tip` or
`internal`. Unlabelled nodes have empty labels, and repeated internal labels are
allowed. Rows are deterministic for the same inputs; neither matching rows nor
matching internal labels imply corresponding nodes between trees.

All metrics and output contents are computed and serialized before creating
output files. Collision checks include all enabled metrics' filenames, symlinks and
hard links when those files would be written. Input errors exit 2 without new
report files; operating-system I/O errors exit 1.

## References

* [DendroPy tree comparisons](https://jeetsukumaran.github.io/DendroPy/library/treecompare.html)
* [DendroPy path distances](https://jeetsukumaran.github.io/DendroPy/library/phylogeneticdistance.html) (background only; not computed by this validator)
* [Diversity background references](../../../docs/README.md#diversity-background)
* [Implementation plan](../../../docs/diversity-tree-validation-plan.md)
