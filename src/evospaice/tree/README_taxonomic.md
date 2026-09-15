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
7. **Export**: Outputs the resulting edges connecting the centroids to a CSV file named after the rank (e.g., `data/mst_edges_genus_centroids.csv`). It also exports a Newick formatted tree file (e.g., `data/mst_genus_centroids.tre.txt`) which is directly comparable to external reference trees.

## Advantages & Use Cases
* Produces a highly interpretable tree that aligns directly with biological taxonomic ranks.
* Greatly reduces computational overhead when visualizing or traversing the graph, as there is exactly one node per resolved taxon.
* Removes noise caused by natural intraspecies variations or redundant sequencing artifacts.

## Handling Missing Taxonomic Data
A significant portion of the Lepidoptera dataset lacks complete taxonomic assignment:
- **Family**: 15,823 missing records
- **Genus**: 58,328 missing records
- **Species**: 80,093 missing records

Because taxonomic clustering requires precise assignments at the target rank, the clustering script intentionally drops any records missing the specified rank. For example, when clustering by species, all 80,093 records lacking a species designation are filtered out and excluded from the Minimum Spanning Tree to ensure the validity of the taxonomic groupings.

### Pruned Dataset Analysis
When checking the IDs from `data/pruned.labels.txt` against the processid column in the TSV data:
- **Total IDs in pruned.labels.txt:** 91,376
- **IDs found in the TSV data:** 61,600 (about 29,776 IDs are missing from the BIN representatives file)

For the 61,600 IDs that are present in the TSV data, the breakdown of missing taxonomic information is:
- **Missing Genus:** 116 records
- **Missing Species:** 197 records

While the vast majority do have species and genus, not all of them do. When clustering, we strictly only use the embeddings that have a valid assigned value for the target rank (e.g., species).
