# Align trees

Prune two Newick trees (or a tree and a metadata table) down to a common
tip set, so trees built from different record subsets — e.g. a sequence-based
reference tree and an embeddings tree — can be compared on exactly the same
tips.

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

## Running

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

## Test fixtures

[`tests/data/overlapping-trees/`](../../../tests/data/overlapping-trees/)
holds the output of running `alignment.py` twice, once per mode:

1. **Tree-vs-tree**: a full unified-taxonomic tree and a full sequence-based
   reference tree were aligned to each other, producing
   `unified_taxonomic_tree_overlap.tre` / `unified_taxonomic_tree_bottom_up_overlap.tre`
   (61,381 tips each) plus a `reference_lepidoptera_overlap.tre` counterpart
   that is **not** checked in — it's only referenced as the input path in the
   reports below.
2. **Tree-vs-metadata**: each `*_overlap.tre` tree from step 1 was pruned
   again against `papilo/papilio_ids.tsv` (146 BOLD process IDs), producing
   the 51-tip `papilo/reference_lepidoptera_papilio.tre` and
   `papilo/unified_taxonomic_tree_bottom_up_papilio.tre`, each with a matching
   `*_report.txt` alignment report.

Regenerate step 2, for example, with:

```bash
python -m evospaice.align_trees.alignment \
  --tree tests/data/overlapping-trees/unified_taxonomic_tree_bottom_up_overlap.tre \
  --metadata tests/data/overlapping-trees/papilo/papilio_ids.tsv \
  --output tests/data/overlapping-trees/papilo/unified_taxonomic_tree_bottom_up_papilio.tre
```
