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