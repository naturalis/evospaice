# Validation report

Render an `evospaice validate` run as a single self-contained HTML page:
the reference and inferred trees drawn as side-by-side dendrograms
(color-coded by shared / inferred-only / reference-only splits) plus a
tip-to-root rank correlation scatter plot. No external JS libraries — SVG
is hand-drawn from the tree topology, only the page's fonts are fetched
externally (Google Fonts).

## Contents

- **`validation_report.py`**: CLI script. Reads the two Newick inputs plus
  the `validation.json` and `tip_to_root_correlation.csv` that
  `evospaice validate --output-dir <dir>` already wrote, and produces one
  HTML file.

## Running

```bash
python -m evospaice.validate.visualization.validation_report \
  --reference tests/data/reference_tree_large_mock.nwk \
  --inferred tests/data/embedding_tree_large_mock.nwk \
  --results-dir results/validation-mock-large2 \
  --output results/validation-mock-large2/report.html \
  --title "Clade Divergence Map"
```

| Flag | Required | Description |
| --- | --- | --- |
| `--reference` | yes | Reference tree (Newick) — same file passed to `evospaice validate --reference`. |
| `--inferred` | yes | Inferred tree (Newick) — same file passed to `evospaice validate --inferred`. |
| `--results-dir` | yes | The `--output-dir` a prior `evospaice validate` run wrote to. Must contain `validation.json` and `tip_to_root_correlation.csv`. |
| `--output` | yes | Path to write the HTML report. |
| `--title` | no (default `Validation Report`) | Browser-tab title. |

Run `evospaice validate` first — this script only renders what's already
on disk, it doesn't recompute anything.

## What it does, step by step

1. **Loads both trees into one shared `TaxonNamespace`** (`dendropy`), so
   the same taxon label means the same object in both trees.
2. **Fixes a leaf order** from the reference tree's own traversal order,
   and uses that same vertical order for both dendrogram panels — so a
   branch that lines up at a different height between the two panels is
   visibly a disagreement.
3. **Lays out each tree** with a small recursive algorithm: a leaf's `x`
   is fixed at the tree's max depth (all leaves flush right); an internal
   node's `x` is set by how many splits separate it from the deepest leaf
   below it (so a shallower node sits further left); every node's `y` is
   the mean of its children's `y` (a leaf's `y` comes straight from the
   fixed order in step 2). This is a plain cladogram — branch lengths are
   not drawn to scale, matching how RF distance itself ignores them.
4. **Classifies every internal branch as shared / inferred-only /
   reference-only**, by comparing each node's leaf-set (its "split") to
   the same computation on the other tree — the same split identity
   [`compare.py`](../compare.py) uses for RF distance itself, so
   the picture and the number it illustrates can't drift apart. Trivial
   splits (single leaves, or the whole tree) aren't classified or colored.
5. **Draws both trees as SVG** — colored branches for shared/inferred-only
   /reference-only splits, a small dot marking where a disagreement
   starts, and inline clade labels (e.g. `E,F,I,J`) on the non-shared
   branches, since a reader can't easily count leaves in a dense diagram.
6. **Draws the tip-to-root scatter plot** from `tip_to_root_correlation.csv`
   — reference rank on x, inferred rank on y (not raw branch-length sums:
   `validation.json`'s own warning notes sums can be in different units
   between trees, so only the *ranks* — what Spearman's rho actually
   measures — are safe to plot against each other). A dashed diagonal
   marks perfect agreement; points off it are tips whose relative
   root-to-tip depth disagrees between the trees.
7. **Assembles one HTML page** — stat tiles (RF, normalized RF, shared/
   inferred-only/reference-only counts, tip-to-root rho), the tree
   comparison, the scatter plot, a written-out list of the non-shared
   clades, and a footer with the exact input paths — and writes it to
   `--output`.
