# Unsupervised Clustering Tree

The `unsupervised_clustering.py` script builds a phylogenetic/minimum spanning tree (MST) directly from individual sequence embeddings without utilizing taxonomic labels during the graph construction process.

## Methodology

1. **Data Loading**: Loads the `.npz` file containing the sequence embeddings and metadata.
2. **Normalization**: Performs L2 normalization on all embeddings to ensure distance calculations are based on cosine similarity logic (when using L2).
3. **HNSW Indexing**: Uses the Faiss library's Hierarchical Navigable Small World (HNSW) index to efficiently compute approximate nearest neighbors.
4. **Graph Construction**: Connects each sequence to its top *k* nearest neighbors (e.g., *k*=15), generating a sparse adjacency matrix of distances.
5. **Minimum Spanning Tree**: Computes the Minimum Spanning Tree (MST) on the adjacency graph to extract a fully connected, cycle-free tree structure representing the relationships.
6. **Export**: Outputs the resulting edges (source, target, distance) and maps the taxonomic metadata back onto the tree for analysis, saving to `data/mst_edges_with_taxonomy.csv`.

## Advantages & Use Cases
* Ideal for discovering novel clades or uncovering cryptic diversity that might be hidden by existing taxonomic classifications.
* Purely relies on the learned representations of the DNA sequences (e.g., from DNABERT or OmniDNA).
* Can show intraspecies variation since every individual sequence is a distinct node in the graph.