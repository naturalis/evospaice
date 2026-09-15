# Taxonomic Clustering Tree

The `taxonomic_clustering.py` script constructs a phylogenetic tree by resolving evolutionary relationships at a specific taxonomic level (species, genus, or family). This minimizes noise and intraspecies variation to produce a cleaner taxonomic tree.

## Usage

You can specify the taxonomic rank you want to cluster by using the `--rank` argument. It defaults to `species`.

```bash
uv run python src/evospaice/tree/taxonomic_clustering.py --rank species
uv run python src/evospaice/tree/taxonomic_clustering.py --rank genus
uv run python src/evospaice/tree/taxonomic_clustering.py --rank family
```

## Methodology

1. **Data Loading**: Loads sequence embeddings and their corresponding taxonomic metadata.
2. **Taxonomic Centroids**: Groups all individual sequence representations by the specified taxonomic rank (e.g., genus). It averages the embeddings for all sequences belonging to the same group to create a single representative "centroid" embedding.
3. **Normalization**: Performs L2 normalization on the calculated centroids.
4. **HNSW Indexing**: Builds a Faiss HNSW index specifically on the set of unique taxonomic centroids rather than individual sequences.
5. **Graph Construction**: Connects each group to its closest neighbors using the index, creating a sparse adjacency matrix.
6. **Minimum Spanning Tree**: Computes the Minimum Spanning Tree (MST) from this matrix to form a cohesive tree at the chosen rank.
7. **Export**: Outputs the resulting edges connecting the centroids to a CSV file named after the rank (e.g., `data/mst_edges_genus_centroids.csv`).

## Advantages & Use Cases
* Produces a highly interpretable tree that aligns directly with biological taxonomic ranks.
* Greatly reduces computational overhead when visualizing or traversing the graph, as there is exactly one node per resolved taxon.
* Removes noise caused by natural intraspecies variations or redundant sequencing artifacts.
