Check that embedding distances are a faithful metric, not just a good identifier: depth-faithfulness, additivity, tip-compression — vs the k-mer baseline.

## Matched-leaf evaluation dataset

Build the evaluation table directly from a Newick tree and the source-side
taxonomy in an MST CSV:

```bash
uv run python -m evospaice.validate.evaluation_dataset \
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

from evospaice.validate.evaluation_dataset import build_evaluation_dataset

summary = build_evaluation_dataset(
    Path("data/pruned.tre"),
    Path("data/mst_edges_with_taxonomy.csv"),
    Path("data/evaluation_dataset.csv"),
)
print(summary.matched_leaves, summary.total_leaves)
```

This produces a source-aligned leaf-level dataset, not tree-comparison scores.
The external dataset referenced by `Target_*` is outside this evaluation join.
