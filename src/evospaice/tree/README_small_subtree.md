# Subtree Extractor (`small_subtree_bottom_up.py`)

## Overview
Comparing massive phylogenetic trees with hundreds of thousands of sequences is visually and computationally difficult. This script allows for a clean, 1:1 topological comparison of specific taxonomic clades across different tree construction methodologies.

Rather than building trees from scratch, this script acts as an **extractor**. It isolates a single target genus (default: `Papilio`) from the fully assembled, massive trees, allowing researchers to evaluate how the AI embeddings structured that specific clade compared to traditional biological references.

## How It Works
1. **Target Identification:** The script loads the dataset's metadata (`.npz` file) and filters for all sequences that belong to the target genus (e.g., `Papilio`). It compiles a strict list of the corresponding sequence IDs.
2. **Tree Loading & Pruning (Shearing):** The script sequentially loads the massive pre-computed trees. For each tree, it uses `skbio`'s `.shear()` method to mathematically prune away all branches and leaves that do not belong to the target sequence list.
3. **Output Generation:** It outputs 1:1 perfectly comparable subtrees, containing the exact same leaves but retaining the topology assigned by each respective pipeline.

## Outputs
When run on the default `Papilio` genus, the script generates three subtree files:
- `data/unified_subtree_Papilio.tre.txt` - The clade extracted from the taxonomy-guided (unified bottom-up) tree.
- `data/unsupervised_subtree_Papilio.tre.txt` - The clade extracted from the purely data-driven (unsupervised K-Means + NJ) tree.
- `data/reference_subtree_Papilio.tre.txt` - The exact same clade extracted from the biological reference tree (`pruned.tre.txt`).

## Use Cases
- **Visual Comparison:** Opening these smaller subtree files in visualization tools like FigTree, iTOL, or Taxonium to manually inspect branching differences.
- **Topological Evaluation:** Feeding these perfectly matched 1:1 subtrees into tree-comparison scripts (e.g., calculating Robinson-Foulds distance or normalized matching clusters) to precisely measure the structural fidelity of the AI embeddings at a localized taxonomic level.