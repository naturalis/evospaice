# Reference vs. embeddings tree: overlap and genus subtrees

How `data/reference_lepidoptera_papilio.tre` and
`data/unified_taxonomic_tree_bottom_up_papilio.tre` were built, how to
reproduce them, and why their RF comparison comes back so high (RF = 0.87,
tip-to-root correlation = 0.05) even though nothing in the pipeline is
broken.

## Inputs

| File | What it is | Tips |
|---|---|---|
| `data/lepidoptera_ground_truth.tre` | Sequence-based reference tree (specimen-level, tip = BOLD process ID, e.g. `FGMLF272-15`) | 91,376 |
| `data/unified_taxonomic_tree_bottom_up.tre.txt` | Embeddings-based tree, built bottom-up with Neighbor-Joining (`src/evospaice/tree/README.md`) | 100,802 |
| `data/unified_taxonomic_tree_bottom_up_metadata.tsv` | The embeddings tree's own metadata: `id, family, genus, species` per tip | 100,802 rows |

The two trees were **not** built from the same specimen set, so before any
genus-level work, they had to be cut down to their shared tips.

## Step 1 — Overlap trees (shared tips only)

RF distance is only defined when both trees have the same tip set. Tool:
[`src/evospaice/tree/prune_reference.py`](src/evospaice/tree/prune_reference.py).

```bash
uv run --no-sync python -m evospaice.tree.prune_reference \
  --tree data/lepidoptera_ground_truth.tre \
  --other-tree data/unified_taxonomic_tree_bottom_up.tre.txt \
  --output data/reference_lepidoptera_overlap.tre \
  --other-output data/unified_taxonomic_tree_bottom_up_overlap.tre \
  --report data/tree_overlap_report.txt
```

What it does: loads both trees with `dendropy`, takes the intersection of
their leaf labels, and calls `tree.retain_taxa_with_labels(...)` on each —
independently — down to that shared set.

Result (`data/tree_overlap_report.txt`):

| | tips |
|---|---|
| Reference tree | 91,376 |
| Embeddings tree | 100,802 |
| **Overlap (kept in both)** | **61,381** |

Output: `data/reference_lepidoptera_overlap.tre` and
`data/unified_taxonomic_tree_bottom_up_overlap.tre` — same 61,381 tip IDs
in both.

## Step 2 — Genus Papilio subset

Goal: a small, matched pair restricted to genus *Papilio*, to inspect one
genus closely.

**2a. Get the Papilio IDs.** Tree tip labels are process IDs, not genus
names, so genus comes from `unified_taxonomic_tree_bottom_up_metadata.tsv`
(column 3 = `genus`):

```bash
printf "id\n" > data/papilio_ids.tsv
awk -F'\t' 'NR>1 && $3=="Papilio"{print $1}' \
  data/unified_taxonomic_tree_bottom_up_metadata.tsv >> data/papilio_ids.tsv
```

→ 146 Papilio IDs. This metadata file covers the embeddings tree's full
100,802-tip universe, which is why it's a safe lookup even though we're
about to prune the *reference* side too.

**2b. Prune both overlap trees to those IDs** (same tool, metadata mode):

```bash
uv run --no-sync python -m evospaice.tree.prune_reference \
  --tree data/reference_lepidoptera_overlap.tre \
  --metadata data/papilio_ids.tsv --id-column id \
  --output data/reference_lepidoptera_papilio.tre \
  --report data/reference_lepidoptera_papilio_report.txt

uv run --no-sync python -m evospaice.tree.prune_reference \
  --tree data/unified_taxonomic_tree_bottom_up_overlap.tre \
  --metadata data/papilio_ids.tsv --id-column id \
  --output data/unified_taxonomic_tree_bottom_up_papilio.tre \
  --report data/unified_taxonomic_tree_bottom_up_papilio_report.txt
```

Only **51** of the 146 Papilio IDs are in the overlap tree — the other 95
exist only in the embeddings tree, and were already dropped at Step 1
before genus filtering ever happened. Both outputs end up with the same 51
tips (verified directly by diffing the tip ID lists).

## Step 3 — Run validate

```bash
evospaice validate \
  --reference data/reference_lepidoptera_papilio.tre \
  --inferred data/unified_taxonomic_tree_bottom_up_papilio.tre \
  --mode unrooted \
  --output-dir results/validation-papilio-unrooted --overwrite
```

`--mode unrooted`, because the embeddings tree is built by Neighbor-Joining
(`src/evospaice/tree/README.md`), an inherently unrooted method — there's
no outgroup or midpoint rule applied, so treating either tree as rooted
would mean comparing an arbitrary root position. `compare.py` ignores
whatever rooting comment (if any) is in the Newick file and sets
`tree.is_rooted` purely from `--mode`.

Result:

```json
{
  "rf": 83,
  "rf_normalized": 0.87,
  "shared": 6,
  "inferred_only": 41,
  "reference_only": 42,
  "inferred_count": 47,
  "reference_count": 48
}
```
tip-to-root correlation: 0.05

## Is this a pipeline bug?

Checked three things before trusting this number:

**1. No corruption from pruning.** Both output trees are well-formed,
(near-)fully bifurcating binary trees — 50 internal nodes / 51 tips
(reference) and 48 internal nodes / 51 tips (embeddings), no collapsed or
degenerate structure. `retain_taxa_with_labels` on a fixed input tree
produces the mathematically exact induced subtree, so this step can't
introduce topology errors on its own.

**2. Species-level pairs agree perfectly.** Of the 51 tips, 45 are the only
representative of their species (nothing to test). The 4 species with
multiple tips — *P. helenus* (3), *P. paris* (2), *P. palinurus* (2),
*P. hermeli* (2) — are monophyletic in **both** trees. No mislabeling, no
scrambled IDs.

**3. Genus-level grouping is (almost) right in both trees, checked against
the full 61,381-tip overlap trees, not just the pruned 51-tip subtree:**

| Tree | Papilio MRCA clade size | Extra non-Papilio taxa pulled in |
|---|---|---|
| Embeddings | 51 | 0 — perfectly monophyletic |
| Reference | 56 | 5 — see below |

The 5 "intruders" in the reference tree are *Heraclides* (3 tips) and
*Pterourus* (2 tips) — both are New World swallowtail genera that many
classifications treat as subgenera of *Papilio* rather than separate
genera. Their appearing inside the Papilio clade in the sequence-based
reference tree is a known, real taxonomic subtlety, not a data error.

**Conclusion:** both trees agree on the coarse structure they can be
checked on (species pairs, genus monophyly). The 87% RF distance and 0.05
correlation come from disagreement in the *fine internal branching order*
among the 47 mostly-singleton Papilio species — i.e. which species is
sister to which. That's a much harder signal to recover than "these are
all Papilio," and COI barcode data (~313–658 bp, one mitochondrial locus)
is well known to have limited power to resolve shallow, recent splits
within a genus. This reads as a genuine limitation of single-locus,
embedding-based NJ trees at fine taxonomic scale — not a mistake in how
these subtrees were built.

If you want higher confidence before drawing conclusions from this,
consider: running the same diagnostic (species/genus monophyly) on a
genus with more within-species replicates, or comparing against a
published Papilionidae phylogeny (multi-gene) rather than this specific
sequence-based reference tree.

## Files this produced

```
data/
├── lepidoptera_ground_truth.tre                       # source: full reference tree (91,376 tips)
├── unified_taxonomic_tree_bottom_up.tre.txt            # source: full embeddings tree (100,802 tips)
├── unified_taxonomic_tree_bottom_up_metadata.tsv        # source: embeddings tree taxonomy (id/family/genus/species)
├── tree_overlap_report.txt                             # Step 1 stats
├── reference_lepidoptera_overlap.tre                   # Step 1 output (61,381 tips)
├── unified_taxonomic_tree_bottom_up_overlap.tre         # Step 1 output (61,381 tips)
├── papilio_ids.tsv                                     # Step 2a: 146 Papilio IDs
├── reference_lepidoptera_papilio_report.txt             # Step 2b stats
├── reference_lepidoptera_papilio.tre                    # Step 2b output (51 tips)
├── unified_taxonomic_tree_bottom_up_papilio_report.txt  # Step 2b stats
└── unified_taxonomic_tree_bottom_up_papilio.tre         # Step 2b output (51 tips)

results/validation-papilio-unrooted/                     # Step 3 output
```

## Reuse

`src/evospaice/tree/prune_reference.py` has two modes:

* `--other-tree` — align two trees to their mutual tip overlap (Step 1).
* `--metadata --id-column <col>` — prune one tree down to any ID list from
  a TSV column (Step 2), e.g. a different genus, family, or a custom
  benchmark set.

```bash
uv run --no-sync python -m evospaice.tree.prune_reference --help
```
