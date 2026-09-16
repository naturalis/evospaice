---
title: Embedding tree validation
description: Topology-only tree comparison with raw and normalized Robinson-Foulds distance
---

## Purpose

Compare an embedding-derived tree with a reference using raw and normalized
Robinson-Foulds (RF) distance. Both scores use topology only:
branch lengths, support values and internal node labels are ignored.

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
denominator and shared/inferred-only/reference-only counts. Each tree must retain
at least one informative rooted clade or unrooted split after taxa alignment and
pruning. If either tree has none, validation reports an input error identifying
the tree and exits with code 2 without writing a report. For example, a star tree
`(A,B,C,D);` is rejected in either mode.

For valid inputs, normalized RF is always numeric.

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

## Whole-tree algorithm-review metrics

The separate `whole_tree` module implements the first, static evaluation pass
from section 4 of `docs/dna-tree-algorithmic-literature-survey.html`. It does not
change the existing topology-only `evospaice validate` command or its output
schema.

```bash
uv run python -m evospaice.validate.whole_tree \
  --inferred results/lepidoptera-centroid-complete/centroid.nwk \
  --reference data/pruned.tre.txt \
  --embeddings /path/to/butterfly-omnidna-leray.npz \
  --pairs 50000 --anchors 128 --neighbors 10 --seed 42 \
  --output-dir results/lepidoptera-centroid-validation
```

The input trees are not modified. Comparison uses their exact, case-sensitive
record-ID intersection, with no genus/family subsampling or BIN remapping.
Every shared ID must have a valid embedding and complete taxonomy. A new
output directory is required. Non-root branch lengths must be finite and
nonnegative on the matched trees; missing lengths are not imputed.

| Review metric | Implemented definition and scope |
| --- | --- |
| RF / normalized RF | Exact informative unrooted split comparison on every matched tip. Normalization uses the sum of observed split counts, including zero-length resolved splits. |
| Kendall-Colijn | Topology-only, lambda = 0: root-to-MRCA **edge counts** plus one unit pendant entry per leaf. Both trees are rooted at the same lexicographically first matched tip edge; unary nodes are suppressed. |
| Normalized KC | Explicit bounded convention: Euclidean difference divided by the sum of the vector norms. This is not a uniquely standardized KC normalization. Uniform sampled pair sums are expanded to the full pair count, so the reported large-cohort distance and normalized ratio are estimates, not exact scores. |
| Taxonomic monophyly/purity | For each taxon, its record count divided by its MRCA subtree's tip count. Uses supplied roots after pruning. Reports all taxa and multi-record taxa separately, plus the fraction with purity exactly one. |
| CPCC-related correlation | Patristic Pearson and Spearman against embedding cosine distance. NJ trees are not ultrametric; these are **not merge-height CPCC** as phrased in the review. |
| Stress | The review's squared relative error, `sum((tree - target)^2) / sum(target^2)`, without a square root. `normalized_stress` is retained as the square-root version used in the earlier centroid report. |
| MAE / MAPE | Absolute error and mean percentage error on sampled pairs. MAPE excludes and counts exactly zero target distances; near-zero targets remain and can dominate. |
| k-NN preservation | Mean overlap/k for uniformly sampled anchors, with exact nearest neighbors searched over **all matched candidates**. Equal computed distances break ties by record ID. Anchor sampling uses seed + 1. |

All sampled quantities are descriptive, not held-out tests. High correlation
alone does not establish low distortion. Reference sequence distances and
centroid cosine-derived lengths have different units: raw reference magnitude
errors are labelled diagnostic only. A separate nonnegative scalar fit is
reported, fitted and evaluated on the same pairs, without claims of biological
calibration.

Centroid taxonomic purity is a construction-constraint check, not independent
accuracy. The sequence reference is an estimate and may share taxonomic
constraints. Supplied-root purity and common-outgroup KC have different,
explicit rooting policies.

Bootstrap support, feature-noise perturbation, and subsampling invariance are
explicitly **not computed** from the two static trees. They require replicate
rebuilds and defined perturbation/assignment rules. Gaussian feature noise is
not equivalent to a classical sequence-site bootstrap. Branch-length KC is
also omitted because the two trees have incompatible length units.

Outputs include an offline `index.html` metrics dashboard, `report.json`,
`taxa.tsv`, `taxon-purity.tsv`, `evaluated-pairs.tsv`, `neighbors.tsv`, and
branch-length-preserving `centroid-matched.nwk` / `reference-matched.nwk`.
The JSON records input hashes, versions, sampling, rooting, definitions,
undefined quantities, and uncomputed metrics.

The implementation uses indexed, vectorized MRCA queries and one candidate
distance vector per neighbor anchor, not a global all-pairs distance matrix.
RF summary mode skips per-split label expansion; the existing detailed
per-clade RF output remains unchanged by default.

```bash
uv run python -m pytest tests/test_whole_tree_metrics.py tests/test_validate.py
```

## Matched-leaf evaluation dataset

Build the evaluation table directly from a Newick tree and the source-side
taxonomy in an MST CSV:

```bash
uv run python -m evospaice.validate.dataset_prep \
  data/pruned.tre \
  data/mst_edges_with_taxonomy.csv \
  --output data/evaluation_dataset.csv
```

The output path must not already exist. The command reports matched and omitted
leaf counts, leaves both inputs unchanged, and publishes the CSV only after all
input records have been checked. Errors produce a nonzero exit code without a
partial output file.

Each output row represents one Newick leaf whose ID occurs in `Source_ID`.
Unmatched leaves are omitted, including IDs found only in `Target_ID`.
Matching is exact and case-sensitive, and rows retain their original Newick
order. Repeated source IDs do not duplicate leaves: their source taxonomy
must agree.

The MST CSV must contain `Source_ID`, `Source_Family`, `Source_Genus`,
and `Source_Species`. These are the only required columns. All `Target_*`
columns refer to a different dataset not stored here: they are neither
required nor used for matching, taxonomy, or conflict checks. Other columns,
including `Distance`, are also ignored. Source taxonomy values are copied
verbatim, including blanks and the literal `None`. An ID match does not imply
that its species name is known.

The Newick input must contain exactly one tree, with unique, nonempty leaf IDs.
Quoted labels and underscores are preserved. Every non-root edge must have a
finite branch length; zero and negative lengths are retained rather than
adjusted. Missing branch lengths are not silently interpreted as zero.
Conflicting source taxonomy, malformed inputs, and no matching leaves are
reported as errors.

### Output columns and their sources

The joined CSV has twelve columns: the original seven Newick measurements and
labels, three source-taxonomy columns, and two per-leaf Newick paths.

| Joined column | Source file | Original field or derivation |
| --- | --- | --- |
| `leaf_id` | `pruned.tre` | Exact leaf label, matched only to `Source_ID`. |
| `branch_length` | `pruned.tre` | Length of the leaf's incoming edge. |
| `distance_from_root` | `pruned.tre` | Sum of edge lengths from the supplied root to the leaf, excluding the root's stem edge. |
| `depth` | `pruned.tre` | Number of edges from that root, including edges through unnamed nodes. |
| `parent_label` | `pruned.tre` | Immediate parent label; blank if unnamed or absent. |
| `nearest_named_ancestor` | `pruned.tre` | Closest labelled ancestor; blank if none exists. |
| `ancestor_labels` | `pruned.tre` | Named ancestors in root-to-parent order, separated by ` > `. |
| `family` | `mst_edges_with_taxonomy.csv` | `Source_Family`. |
| `genus` | `mst_edges_with_taxonomy.csv` | `Source_Genus`. |
| `species` | `mst_edges_with_taxonomy.csv` | `Source_Species`. |
| `tree_newick` | `pruned.tre` | Only this leaf and its full ancestor path, with original labels and branch lengths. |
| `taxonomy_newick` | `mst_edges_with_taxonomy.csv` | `Source_Family` -> `Source_Genus` -> `Source_Species` -> `Source_ID`, with no branch lengths. |

**Join key:** `leaf_id = Source_ID`. Only the matching source record supplies
the taxonomy; `Source_ID` is represented by `leaf_id`, not a separate output
column. Only source-matched leaves are kept, with one row per leaf.

**MST fields not included:** all `Target_*` columns, `Distance`, and the
source-target connections. Both `branch_length` and `distance_from_root` come
only from the Newick tree, not from MST distances.

A single-leaf tree has depth and root distance zero; its `branch_length` is
blank if the root has no stem length. The tool does not infer a biological root
for an unrooted tree: root-dependent values follow the supplied representation.

### Per-leaf Newick paths

Both new columns contain a complete, semicolon-terminated Newick statement
with exactly one leaf. Labels are quoted and escaped when necessary to
preserve spaces, punctuation, apostrophes, and underscores.

`tree_newick` removes all sibling branches but retains every ancestor,
including unnamed nodes and the original root. It preserves the length of
each remaining edge, including the root's stem if present, without collapsing
unary nodes or summing their lengths. Only labels and lengths are emitted;
comments and annotations are not included.

For example, the original tree:

```text
((A:0.1,B:0.2)Parent:0.3)Root:0.0;
```

produces this `tree_newick` value for leaf `A`:

```text
((A:0.1)Parent:0.3)Root:0.0;
```

`taxonomy_newick` starts at the family and ends at the matching `Source_ID`.
For source taxonomy `FamilyA`, `GenusA`, `SpeciesA`, and ID `A`, it contains:

```text
(((A)SpeciesA)GenusA)FamilyA;
```

This is taxonomy topology only, not a reconstruction of the MST. The current
CSV provides no taxonomic parent-child branch lengths, and its `Distance`
values describe source-target pairs; repeated source IDs may have different
values. No minimum, mean, zero, or length from the original Newick tree is
substituted. Taxonomy branch lengths remain unspecified until suitable input
data and a mapping for those lengths are provided.

Missing taxonomy labels retain their rank positions as unnamed nodes. The
recognized placeholders are blank, `None`, `null`, `NA`, `n/a`, `nan`,
`unknown`, and `-` (case-insensitive, ignoring surrounding whitespace).
The separate `family`, `genus`, and `species` columns still preserve the
original values verbatim.

For Python callers:

```python
from pathlib import Path

from evospaice.validate.dataset_prep import build_evaluation_dataset

summary = build_evaluation_dataset(
    Path("data/pruned.tre"),
    Path("data/mst_edges_with_taxonomy.csv"),
    Path("data/evaluation_dataset.csv"),
)
print(summary.matched_leaves, summary.total_leaves)
```

This produces a source-aligned leaf-level dataset, not tree-comparison scores.
The external dataset referenced by `Target_*` is outside this evaluation join.
