# Unsupervised Neighbor-Joining Tree (`unsupervised_nj_tree.py`)

## Overview
This script implements a **Purely Unsupervised, Data-Driven NJ Approach**. It completely ignores human taxonomic labels but, unlike the MST script, it generates a mathematically rigorous, full phylogenetic tree using Neighbor-Joining.

## How It Works
Because Neighbor-Joining is computationally intensive ($O(N^3)$), running it directly on 181,000+ sequences is practically impossible. This script uses a fast clustering trick:
1. **Unsupervised Pseudo-Species (K-Means):** It uses FAISS spherical K-Means to divide the sequence embeddings into a fixed number of mathematically similar clusters (e.g., $K=2000$). These act as data-driven "pseudo-species" centroids.
2. **Backbone Neighbor-Joining:** It computes a Cosine distance matrix for those 2,000 unsupervised centroids and runs `skbio.tree.nj` (Neighbor-Joining). This builds a complete, unconstrained, bifurcating phylogenetic backbone.
3. **Sequence Grafting:** Every single sequence in the dataset is then grafted onto its assigned cluster centroid node. The branch length is determined by the sequence's exact Cosine distance from the centroid. The leaf names are set to the exact `source_id` (e.g., `FGMLF272-15`), ensuring compatibility with traditional sequence-based trees.

## Outputs
- `data/unsupervised_nj_tree.tre.txt` - A fully unconstrained, data-driven Newick tree representing the geometry of the embeddings without human taxonomic bias.

## Use Cases
- **Comparing Against Taxonomy:** Validating how closely the language model's pure mathematical interpretation of DNA sequence evolution maps to traditional, human-assigned evolutionary trees.
- **Novel Discovery:** Uncovering deep evolutionary relationships or cryptic splits that are completely missed by traditional taxonomy.