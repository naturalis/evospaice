# Unified Hierarchical Tree (`unified_hierarchical_tree.py`)

## Overview
This script implements a **Taxonomy-Guided Hybrid Approach** to construct a massive, biologically sound phylogenetic tree from sequence embeddings. It combines hard taxonomic constraints at higher ranks with soft, data-driven embedding placements at lower ranks.

## How It Works
1. **Hard Constraints (Family Level):** 
   - Averages the sequence embeddings for each Family to compute a centroid.
   - Builds a rigid backbone by calculating Cosine distances between these Family centroids and applying UPGMA clustering.
2. **Soft Constraints (Genus & Species Levels):** 
   - For every Family, it computes the Cosine distance matrix of its Genus centroids and runs Neighbor-Joining (NJ) to attach the Genera sub-clades.
   - It then repeats this process, running NJ on the Species centroids within each Genus to attach the Species sub-clades.
3. **Sequence Grafting:** 
   - Individual sequence embeddings are dynamically grafted onto their assigned Species leaves.
   - The branch length for each sequence is its exact Cosine distance from the Species centroid.
   - The leaf names are set to the exact `source_id` (e.g., `FGMLF272-15`), making the tree compatible with traditional sequence-based validation trees like `pruned.tre.txt`.

## Outputs
- `data/unified_taxonomic_tree.tre.txt` - A complete, full-scale Newick phylogenetic tree that adheres to Family $\rightarrow$ Genus $\rightarrow$ Species taxonomy while letting the AI embeddings dictate the structural relationships within those ranks.

## Use Cases
- **Generating Reference Trees:** Producing a finalized, publishable tree that biologists expect to see (guided by higher-level taxonomy).
- **Evaluating Downstream Pipelines:** Useful for calculating phylogenetic diversity metrics where a single unified tree is required.