# Phylogenetic tree visualization

The reference image in [`images/phylogentic_tree.png`](../../../images/phylogentic_tree.png)
is a 3D hyperbolic fisheye projection produced with
[Walrus](https://www.caida.org/catalog/software/walrus/). It is useful as an
overview of a very dense tree, but a modern viewer also needs search, clade
collapse, metadata, and progressive exploration.

## Available tools

| Tool | Best use | Practical scale | Notes |
| --- | --- | --- | --- |
| [Taxonium](https://github.com/theosanderson/taxonium) | Interactive exploration of the complete tree | Millions of tips | Browser-based search and metadata; proven on multi-million-node trees. |
| [iTOL](https://itol.embl.de/) | Polished figures and annotated circular or unrooted trees | Large trees | Reads Newick directly; supports clade collapse, branch lengths, datasets, and SVG/PDF/PNG export. Some automation and saved views require a subscription. |
| [phylotree.js](https://github.com/veg/phylotree.js) | Embedding an interactive tree in a custom web application | Thousands of tips | Newick parser, radial and linear layouts, zoom, rerooting, selection, and clade collapse. SVG rendering limits full-tree scale. |
| [Cytoscape.js](https://js.cytoscape.org/) | Highly customized network interaction | Medium to large graphs | Flexible canvas renderer and interaction API, but phylogenetic layout and Newick conversion must be supplied. Dash Cytoscape provides Python integration. |
| [ETE Toolkit](https://etetoolkit.org/) | Python tree processing and static rendering | Small to medium trees | Good for scripts and annotated exports, not million-tip browser exploration. |
| [Toytree](https://eaton-lab.org/toytree/) | Python and notebook figures | Small to medium trees | Concise publication-oriented plotting. |
| [Biopython Phylo](https://biopython.org/wiki/Phylo) | Simple static diagnostics | Small trees | Already fits the Python stack, but is not an interactive large-tree viewer. |
| [ggtree](https://bioconductor.org/packages/ggtree/) | Publication-quality annotated figures in R | Small to medium trees | Strong grammar for combining trees with biological datasets. |
| [OneZoom](https://www.onezoom.org/) | Fractal, zoomable tree-of-life presentation | Very large trees | Strong storytelling model, but less suitable as a drop-in application library. |
| [D3 hierarchy](https://d3js.org/d3-hierarchy) with [Three.js](https://threejs.org/) | A custom Walrus-like 3D experience | Application-specific | Maximum visual control, with substantial layout, level-of-detail, and interaction engineering. |

## Recommendation

Use different tools for different deliverables:

1. Use **Taxonium** to evaluate interactive exploration of the complete tree.
2. Use **iTOL** for polished circular or unrooted figures and presentation assets.
3. Use **phylotree.js** for an embedded viewer of selected genus- or family-sized clades.
4. Build with **Three.js** only if the 3D fisheye appearance is itself a required deliverable.

The runnable [Taxonium prototype](taxonium/) automatically loads the repository's
`data/pruned.tre.txt` tree for local exploration.

The pipeline's Newick output can be consumed directly by Taxonium, iTOL,
phylotree.js, ETE, and Biopython. Metadata should remain keyed by stable leaf and
internal-node identifiers so it can be exported as viewer-specific annotation
files without changing the tree.

## Evaluation plan

Benchmark each candidate with the same progressively larger Newick files. Record
initial load time, peak memory, pan and zoom responsiveness, search latency,
clade-collapse behavior, branch-length fidelity, metadata support, and export
quality. Start with a genus or family, then test 10,000, 100,000, and one million
tips. A viewer that cannot render the full tree should degrade through
server-side subtree extraction or pre-collapsed clades rather than sending every
tip to the browser.
