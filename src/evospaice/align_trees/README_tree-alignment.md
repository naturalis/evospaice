# Align trees

Prune two Newick trees (or a tree and a metadata table) down to a common
tip set, so trees built from different record subsets — e.g. a sequence-based
reference tree and an embeddings tree — can be compared on exactly the same
tips. Then, optionally, narrow either tree down to one taxonomic group (a
genus, a family, a species...) to inspect it closely.

## Contents

- **`alignment.py`**: CLI script that computes tip overlap, prunes, and
  writes a stats report. Two modes, selected by which source flag is given:
  - **Tree-vs-tree** (`--other-tree`): intersects the tip labels of `--tree`
    and `--other-tree`, prunes both down to the overlap, and writes both
    pruned trees plus a comparison report.
  - **Tree-vs-metadata** (`--metadata`): prunes `--tree` down to the IDs
    listed in a TSV's id column, and writes the pruned tree plus a report
    noting any metadata IDs that were not found in the tree.

  Either mode reports tip counts for each side, the overlap size (as a
  percentage of each side), and how many tips were dropped from each side.

- **`taxon_subtree.py`**: CLI script that prunes one tree down to a single
  taxonomic group at any rank (genus, family, species, ...). It's a thin
  layer over `alignment.py`'s tree-vs-metadata mode: instead of a
  pre-built ID list, you give it a taxonomy TSV plus a rank column and a
  value (e.g. `--rank genus --value Papilio`); it derives the ID list
  itself, saves it for reuse, and prunes the tree with the same underlying
  functions `alignment.py` uses.

## Running `alignment.py`

```bash
python -m evospaice.align_trees.alignment \
  --tree reference.tre --other-tree embeddings.tre \
  --output reference.pruned.tre --other-output embeddings.pruned.tre
```

```bash
python -m evospaice.align_trees.alignment \
  --tree reference.tre --metadata ids.tsv \
  --output reference.pruned.tre
```

| Flag | Required | Description |
| --- | --- | --- |
| `--tree` | yes | First tree to align (Newick). |
| `--output` | yes | Path to write the pruned `--tree`. |
| `--other-tree` | one of `--other-tree` / `--metadata` | Second tree to align against (Newick). |
| `--metadata` | one of `--other-tree` / `--metadata` | TSV with an id column of tips to keep instead. |
| `--other-output` | with `--other-tree` | Path to write the pruned `--other-tree`. |
| `--id-column` | no (default `id`) | Column in `--metadata` holding tip IDs. |
| `--report` | no (default `<output>_report.txt`) | Path for the stats report. |

## Running `taxon_subtree.py`

```bash
python -m evospaice.align_trees.taxon_subtree \
  --tree overlap.tre --metadata taxonomy.tsv \
  --rank genus --value Papilio \
  --output papilio.tre
```

| Flag | Required | Description |
| --- | --- | --- |
| `--tree` | yes | Tree to prune (Newick). |
| `--metadata` | yes | TSV with taxonomy columns, e.g. `id, family, genus, species`. |
| `--rank` | yes | Metadata column to filter on, e.g. `genus`, `family`, `species`. |
| `--value` | yes | Value to match in `--rank`, e.g. `Papilio`. Exact, case-sensitive match. |
| `--output` | yes | Path to write the pruned tree. |
| `--id-column` | no (default `id`) | Metadata column holding tip IDs. |
| `--ids-output` | no (default `<output>_ids.tsv`) | Where to save the matched ID list. |
| `--report` | no (default `<output>_report.txt`) | Path for the stats report. |

What it does, step by step:

1. Reads `--metadata` and keeps the `--id-column` value of every row where
   `--rank` equals `--value` (e.g. every row with `genus == "Papilio"`).
2. Writes that ID list to `--ids-output` — a plain TSV with an `id` header,
   one ID per line. This is saved on its own so the exact same subset can
   be rebuilt later (fed back into `alignment.py --metadata`, or into a
   different tree) without re-deriving it from the full metadata table.
3. Loads `--tree`, intersects its tip labels with the ID list, and calls
   `dendropy`'s `tree.retain_taxa_with_labels(...)` to prune everything
   else — the same pruning function `alignment.py` uses.
4. Writes the pruned tree to `--output` and a stats report to `--report`:
   how many tips were in the input tree, how many IDs matched the filter,
   the overlap, and (if any) example IDs from the filter that weren't
   found in the tree.

A tree pruned this way is only as good as the metadata it's pruned
against — if `--metadata` only covers part of the tree's tip universe
(see the worked example below), most matches for a rare group can be lost
before the taxon filter is even applied.

## Worked example: genus Papilio, end to end

This reproduces the checked-in files under
[`tests/data/overlapping-trees/`](../../../tests/data/overlapping-trees/)
from the two raw source trees, using files already in this repo.

**Inputs:**

| File | What it is | Tips |
|---|---|---|
| [`data/reference_lepidoptera.tre.txt`](../../../data/reference_lepidoptera.tre.txt) | Sequence-based reference tree (tip = BOLD process ID, e.g. `FGMLF272-15`) | 91,376 |
| [`tests/data/unified_taxonomic_tree_bottom_up.tre.txt`](../../../tests/data/unified_taxonomic_tree_bottom_up.tre.txt) | Embeddings-based tree, built bottom-up with Neighbor-Joining (`src/evospaice/tree/README.md`) | 100,802 |
| [`tests/data/unified_taxonomic_tree_bottom_up_metadata.tsv`](../../../tests/data/unified_taxonomic_tree_bottom_up_metadata.tsv) | The embeddings tree's own taxonomy: `id, family, genus, species` per tip | 100,802 rows |

**Step 1 — align the two full trees to their shared tips.** The reference
and embeddings trees weren't built from the same specimen set, so before
any genus-level work they need a common tip set. RF distance (and any
other topology comparison) is only defined when both trees have the same
tips.

```bash
python -m evospaice.align_trees.alignment \
  --tree data/reference_lepidoptera.tre.txt \
  --other-tree tests/data/unified_taxonomic_tree_bottom_up.tre.txt \
  --output tests/data/overlapping-trees/reference_lepidoptera_overlap.tre \
  --other-output tests/data/overlapping-trees/unified_taxonomic_tree_bottom_up_overlap.tre \
  --report tests/data/overlapping-trees/tree_overlap_report.txt
```

→ 61,381 tips kept on both sides (67.2% of the 91,376-tip reference tree,
60.9% of the 100,802-tip embeddings tree). Only
[`unified_taxonomic_tree_bottom_up_overlap.tre`](../../../tests/data/overlapping-trees/unified_taxonomic_tree_bottom_up_overlap.tre)
is checked in; the reference-side output is regenerated by the command
above rather than committed.

**Step 2 — narrow the overlap tree to genus Papilio.** Tip labels are
process IDs, not genus names, so genus has to come from the metadata
table:

```bash
python -m evospaice.align_trees.taxon_subtree \
  --tree tests/data/overlapping-trees/unified_taxonomic_tree_bottom_up_overlap.tre \
  --metadata tests/data/unified_taxonomic_tree_bottom_up_metadata.tsv \
  --rank genus --value Papilio \
  --output tests/data/overlapping-trees/papilo/unified_taxonomic_tree_bottom_up_papilio.tre \
  --ids-output tests/data/overlapping-trees/papilo/papilio_ids.tsv \
  --report tests/data/overlapping-trees/papilo/unified_taxonomic_tree_bottom_up_papilio_report.txt
```

This is exactly how
[`papilio_ids.tsv`](../../../tests/data/overlapping-trees/papilo/papilio_ids.tsv)
was produced — it wasn't hand-written, it's `taxon_subtree.py`'s
`--ids-output` from this run. 146 metadata rows have `genus == "Papilio"`,
but only **51** of those IDs are in the overlap tree — the other 95 exist
only in the full embeddings tree, and were already dropped at Step 1
before genus filtering ever ran.

**Step 3 — do the same for the reference side**, using the *same* ID list
(`--ids-output` isn't repeated — `alignment.py --metadata` reads back the
file `taxon_subtree.py` just wrote):

```bash
python -m evospaice.align_trees.alignment \
  --tree tests/data/overlapping-trees/reference_lepidoptera_overlap.tre \
  --metadata tests/data/overlapping-trees/papilo/papilio_ids.tsv \
  --output tests/data/overlapping-trees/papilo/reference_lepidoptera_papilio.tre \
  --report tests/data/overlapping-trees/papilo/reference_lepidoptera_papilio_report.txt
```

Both trees now have the same 51 tips — ready to compare with
`evospaice validate`:

```bash
evospaice validate \
  --reference tests/data/overlapping-trees/papilo/reference_lepidoptera_papilio.tre \
  --inferred tests/data/overlapping-trees/papilo/unified_taxonomic_tree_bottom_up_papilio.tre \
  --mode unrooted \
  --output-dir results/validation-papilio-unrooted
```

`--mode unrooted` because the embeddings tree is built by Neighbor-Joining
(`src/evospaice/tree/README.md`), an inherently unrooted method with no
outgroup or midpoint rule applied — treating either tree as rooted would
mean comparing an arbitrary root position.

## Test fixtures

[`tests/data/overlapping-trees/`](../../../tests/data/overlapping-trees/)
holds the output of the worked example above:

- **`unified_taxonomic_tree_overlap.tre`** / **`unified_taxonomic_tree_bottom_up_overlap.tre`**
  (61,381 tips each) — Step 1 output, tree-vs-tree mode. Their
  `reference_lepidoptera_overlap.tre` counterpart is **not** checked in;
  it's only referenced as an input path in the reports below it, and is
  regenerated by the Step 1 command above.
- **`papilo/`** — Step 2/3 output, tree-vs-metadata mode: the 51-tip
  `papilo/reference_lepidoptera_papilio.tre` and
  `papilo/unified_taxonomic_tree_bottom_up_papilio.tre`, each with a
  matching `*_report.txt`, plus `papilo/papilio_ids.tsv` (the 146-ID list
  `taxon_subtree.py` derived from the metadata table).

Regenerate the Papilio subset, for example, with:

```bash
python -m evospaice.align_trees.alignment \
  --tree tests/data/overlapping-trees/unified_taxonomic_tree_bottom_up_overlap.tre \
  --metadata tests/data/overlapping-trees/papilo/papilio_ids.tsv \
  --output tests/data/overlapping-trees/papilo/unified_taxonomic_tree_bottom_up_papilio.tre
```

Or regenerate `papilio_ids.tsv` itself, or build a subset for a different
rank/value entirely, with `taxon_subtree.py` — see the worked example above.
