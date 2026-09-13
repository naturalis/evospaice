Render a generated Newick tree as a static PNG with Biopython and Matplotlib:

```powershell
evospaice viz `
	--tree output/scaled-tree.nwk `
	--output output/scaled-tree.png `
	--show-branch-lengths
```

The horizontal axis uses the fitted embedding-distance branch lengths. It does
not represent evolutionary time or substitutions per site.

Terminal labels are shown by default. Add `--show-internal-labels` for a
diagnostic rendering of named taxonomy nodes; unary zero-length taxonomy chains
can cause those internal labels to overlap.
