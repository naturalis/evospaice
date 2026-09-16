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
unmatched counts. The viewer automatically zooms to all matching tips; use
**Reset zoom** to return to the full tree. This compares leaf membership; it
does not graft or display the subtrees' internal topology. Independently
generated trees therefore need stable, shared tip identifiers.

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
