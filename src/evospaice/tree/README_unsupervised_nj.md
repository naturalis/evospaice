# Unsupervised Neighbor-Joining Tree (`unsupervised_nj_tree.py`)

## Overview
This script implements a **Purely Unsupervised, Data-Driven NJ Approach**. It completely ignores human taxonomic labels but generates a mathematically rigorous, full phylogenetic tree using a bottom-up Neighbor-Joining methodology.

## How It Works
Because Neighbor-Joining is computationally intensive ($O(N^3)$), running it directly on 181,000+ sequences is practically impossible. This script uses a bottom-up hierarchical clustering trick:
1. **Unsupervised Pseudo-Species (K-Means):** It uses FAISS spherical K-Means to divide the sequence embeddings into a fixed number of mathematically similar clusters (e.g., $K=2000$). These act as data-driven "pseudo-species" centroids.
2. **Cluster Subtrees (Bottom-Up):** For each cluster, it builds a local sub-tree from the constituent sequence embeddings using Neighbor-Joining.
3. **Backbone Neighbor-Joining:** It computes a Cosine distance matrix for the 2,000 unsupervised centroids and runs `skbio.tree.nj` (Neighbor-Joining). This builds a complete, unconstrained, bifurcating phylogenetic backbone.
4. **Subtree Grafting & Rooting:** The local cluster subtrees are grafted onto the corresponding nodes of the backbone. Finally, the entire assembled structure is rooted using midpoint rooting (`.root_at_midpoint()`) to ensure balanced evolutionary distance visualization without branch distortion.

## Outputs
- `data/unsupervised_nj_tree_midpoint.tre.txt` - A fully unconstrained, data-driven Newick tree representing the geometry of the embeddings without human taxonomic bias, assembled via bottom-up NJ clustering.

## Use Cases
- **Comparing Against Taxonomy:** Validating how closely the language model's pure mathematical interpretation of DNA sequence evolution maps to traditional, human-assigned evolutionary trees.
- **Novel Discovery:** Uncovering deep evolutionary relationships or cryptic splits that are completely missed by traditional taxonomy.