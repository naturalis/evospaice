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

The browser downloads the pinned Taxonium and React modules from `esm.sh` at
runtime. Node.js and a local package installation are not required.

## View an inferred genus

Extract a genus from a centroid-baseline run, retaining original IDs in one
Newick and adding readable species labels in a separate display copy:

```bash
uv run python -m evospaice.viz.taxonium.extract_clade \
  --tree /path/to/butterfly-centroid/centroid.nwk \
  --metadata /path/to/butterfly-centroid/selected-records.tsv \
  --clade genus:Papilio \
  --output-dir results/papilio-centroid
```

Start the same launcher bound to localhost:

```bash
python3 src/evospaice/viz/taxonium/serve.py --host 127.0.0.1 --port 8767
```

Open
<http://localhost:8767/src/evospaice/viz/taxonium/?tree=/results/papilio-centroid/species-labels.nwk&title=Papilio%20centroid%20baseline>.
The `tree` parameter must resolve to the same HTTP origin. Omitting it retains
the original reference-tree default. `title` changes the browser tab label.
The centroid view is an inferred baseline, not the independent reference
phylogeny. The extraction resets only the genus's external stem length;
internal paths are unchanged.