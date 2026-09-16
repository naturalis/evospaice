# Taxonium prototype

This no-build prototype embeds
[`taxonium-component`](https://www.npmjs.com/package/taxonium-component) and
automatically loads [`data/pruned.tre.txt`](../../../../data/pruned.tre.txt)
as Newick data.

From the repository root, run:

```bash
python3 src/evospaice/viz/taxonium/serve.py
```

Then open <http://localhost:8000/src/evospaice/viz/taxonium/>. The server must
run from this launcher because the viewer and tree need to share one HTTP
origin; opening `index.html` directly will not allow it to fetch the tree.

The viewer initially loads `data/pruned.tre.txt`. Use **Reference tree** in the
header to view another local Newick file (`.nwk`, `.newick`, `.tree`, `.tre`,
or `.txt`). Selected files stay in the browser and are not uploaded.

Use **Add a sample to compare** to load one or more Newick subtrees. Matching
tip labels are colored by sample, and the sample bar reports matched and
unmatched counts. Clear a sample's checkbox to exclude it from the colors,
counts, search, and overlap calculation without removing its uploaded file;
select it again to restore it. The viewer automatically zooms to all matching
tips; use **Reset zoom** to return to the full tree. This compares leaf
membership; it does not graft or display the subtrees' internal topology.
Independently generated trees therefore need stable, shared tip identifiers.

Tips present in multiple included samples are colored black as **Overlap (N)**,
where `N` is the number of sample memberships. Use the **overlapping tips**
control in the sample bar to list exact process IDs and participating samples.
Choose **Show overlap only** to display their induced tree, then **Show full
tree** to restore the reference.

To isolate a clade, select two nodes in the tree and choose **Focus subtree**.
The viewer displays only their most recent common ancestor and its descendants.
Choose **Show full tree** to restore the reference. Selecting another node when
two are already queued starts a new pair.

When a node is selected, its **Branch length** is included in Taxonium's
metadata details. The value is the immediate Newick edge length from that node
to its parent, not its cumulative distance from the root.

The default pruned tree is enriched with species names from
`data/pruned.taxonomy.tsv`. This lookup is generated from
`unified_taxonomic_tree.tre.txt`; it does not replace the displayed reference
tree. Process IDs absent from the unified tree simply have no species value.

The browser downloads the pinned Taxonium and React modules from `esm.sh` at
runtime. Node.js and a local package installation are not required.

The Naturalis symbol in the header is vendored from
<https://large-scale-blast.naturalis.io/naturalis-logo.svg>.
