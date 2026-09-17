import numpy as np
import pandas as pd
from skbio.tree import TreeNode
import sys
import os

sys.setrecursionlimit(100000)

def sanitize_name(name):
    return str(name).replace(":", "_").replace("(", "_").replace(")", "_").replace(",", "_").replace(";", "_").replace(" ", "_")

def extract_subtree_for_genus(target_genus="Papilio",
                              unified_tree_path='data/unified_taxonomic_tree_bottom_up.tre.txt',
                              unsupervised_tree_path='data/unsupervised_nj_tree_midpoint.tre.txt',
                              reference_tree_path='data/pruned.tre.txt',
                              metadata_path='data/dnabert-s_BOLD_Public.30-Jun-2026-Lepidoptera-BIN-representatives.npz'):
    """
    Extracts a subtree for a given genus from the pre-computed massive trees
    (unified, unsupervised, and reference) by identifying all sequence IDs
    belonging to the genus and pruning the trees down to those leaves.
    """
    print(f"Loading metadata from {metadata_path}...")
    data = np.load(metadata_path, allow_pickle=True)
    
    ids = data['ids']
    genus = data['genus']
    
    df = pd.DataFrame({
        'id': ids,
        'genus': genus
    })

    # 1. Identify all sequence IDs for the target genus
    valid_mask = (df['genus'] == target_genus)
    df_valid = df[valid_mask].copy()
    
    if len(df_valid) == 0:
        print(f"Error: No sequences found for genus '{target_genus}'.")
        return

    # Keep track of sanitized IDs since tree tips will have sanitized names
    target_ids = df_valid['id'].apply(sanitize_name).tolist()
    target_ids_set = set(target_ids)
    print(f"Found {len(target_ids)} sequences for genus '{target_genus}'.")

    # Helper function to load and shear a tree
    def process_tree(tree_path, output_name):
        if not os.path.exists(tree_path):
            print(f"Warning: Tree file not found: {tree_path}")
            return
            
        print(f"Loading tree: {tree_path}...")
        tree = TreeNode.read(tree_path, format='newick')
        
        # Verify which tips actually exist in the tree
        existing_tips = set(tip.name for tip in tree.tips())
        tips_to_keep = list(target_ids_set.intersection(existing_tips))
        
        if not tips_to_keep:
            print(f"Error: None of the sequence IDs for {target_genus} were found in {tree_path}.")
            return
            
        print(f"Shearing (pruning) tree to {len(tips_to_keep)} matching leaves...")
        sub_tree = tree.shear(tips_to_keep)
        
        # Save output
        output_file = f'data/{output_name}_{sanitize_name(target_genus)}.tre.txt'
        print(f"Writing pruned tree to {output_file}...")
        sub_tree.write(output_file, format="newick")

    # 2. Extract from Unified Tree
    process_tree(unified_tree_path, "unified_subtree")
    
    # 3. Extract from Unsupervised Tree
    process_tree(unsupervised_tree_path, "unsupervised_subtree")
    
    # 4. Extract from Reference (Pruned) Tree
    process_tree(reference_tree_path, "reference_subtree")

if __name__ == "__main__":
    extract_subtree_for_genus(target_genus="Papilio")
