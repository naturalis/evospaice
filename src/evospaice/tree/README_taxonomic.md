# Taxonomic Clustering Tree

The `taxonomic_clustering.py` script constructs a phylogenetic tree by resolving evolutionary relationships at the species level, effectively minimizing noise and intraspecies variation to produce a cleaner taxonomic tree.

## Methodology

1. **Data Loading**: Loads sequence embeddings and their corresponding taxonomic metadata.
2. **Species Centroids**: Groups all individual sequence representations by their assigned species name. It averages the embeddings for all sequences belonging to the same species to create a single representative "centroid" embedding.
3. **Normalization**: Performs L2 normalization on the calculated species centroids.
4. **HNSW Indexing**: Builds a Faiss HNSW index specifically on the set of unique species centroids rather than individual sequences.
5. **Graph Construction**: Connects each species to its closest species neighbors using the index, creating a sparse adjacency matrix.
6. **Minimum Spanning Tree**: Computes the Minimum Spanning Tree (MST) from this matrix to form a cohesive, species-level tree.
7. **Export**: Outputs the resulting edges connecting the species centroids to `data/mst_edges_species_centroids.csv`.

## Advantages & Use Cases
* Produces a highly interpretable, classic "Species Tree" that aligns directly with biological taxonomic ranks.
* Greatly reduces computational overhead when visualizing or traversing the graph, as there is exactly one node per resolved species.
* Removes noise caused by natural intraspecies variations or redundant sequencing artifacts.