import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist
from scipy.cluster.hierarchy import linkage, to_tree
from skbio.tree import TreeNode
import faiss
import sys

sys.setrecursionlimit(100000)

def sanitize_name(name):
    return str(name).replace(":", "_").replace("(", "_").replace(")", "_").replace(",", "_").replace(";", "_").replace(" ", "_")

def build_top_down_backbone(target_genus="Papilio"):
    """
    Builds a small tree top-down for a SINGLE Genus by calculating Species
    centroids within that genus and clustering them into a backbone.
    """
    file_path = 'data/dnabert-s_BOLD_Public.30-Jun-2026-Lepidoptera-BIN-representatives.npz'
    print(f"Loading data from {file_path}...")
    data = np.load(file_path, allow_pickle=True)
    
    embeddings = data['embeddings'].astype(np.float32)
    ids = data['ids']
    genus = data['genus']
    species = data['species']
    
    df = pd.DataFrame({
        'id': ids,
        'genus': genus,
        'species': species,
        'idx': np.arange(len(ids))
    })

    # Filter for the specific genus and ensure species is present
    valid_mask = (df['genus'] == target_genus) & \
                 (df['species'] != "") & (df['species'].notna()) & (df['species'] != "nan")
    df_valid = df[valid_mask].copy()
    
    if len(df_valid) == 0:
        print(f"Error: No valid data found for genus {target_genus}.")
        return

    print(f"Building top-down backbone for the Species within {target_genus}.")

    # 1. Compute Species Centroids (Stepping one level down from Genus)
    print("Computing Species Centroids...")
    species_centroids = {}
    for sp_name, group in df_valid.groupby('species'):
        sp_indices = group['idx'].values
        species_centroids[sp_name] = np.mean(embeddings[sp_indices], axis=0)
        
    sp_names = list(species_centroids.keys())
    sp_matrix = np.array(list(species_centroids.values()), dtype=np.float32)
    
    # Normalize for cosine distance
    faiss.normalize_L2(sp_matrix)
    
    # 2. Build the top-down hierarchy (Agglomerative Clustering / UPGMA)
    print("Clustering Species to build the genus backbone...")
    fam_dists = pdist(sp_matrix, metric='cosine')
    
    # Using 'average' linkage (UPGMA) which is standard for phylogenetic distances
    fam_Z = linkage(fam_dists, method='average')
    
    def _build_skbio_tree(node, sp_names):
        """Recursively converts scipy linkage tree to skbio TreeNode"""
        if node.is_leaf():
            sp_name = sp_names[node.id]
            t = TreeNode(name=sanitize_name(sp_name))
            t.original_name = sp_name
            return t
        
        left_tree = _build_skbio_tree(node.get_left(), sp_names)
        right_tree = _build_skbio_tree(node.get_right(), sp_names)
        
        # Split distance evenly between branches
        left_tree.length = max(0.0, float(node.dist) / 2.0)
        right_tree.length = max(0.0, float(node.dist) / 2.0)
        
        parent = TreeNode()
        parent.append(left_tree)
        parent.append(right_tree)
        return parent

    # Add a root node for the genus itself
    root = TreeNode(name=sanitize_name(target_genus))
    backbone_tree = _build_skbio_tree(to_tree(fam_Z), sp_names)
    root.append(backbone_tree)
    
    # 3. Output
    output_file = f'data/small_tree_top_down_{sanitize_name(target_genus)}.tre.txt'
    print(f"Writing top-down backbone tree to {output_file}...")
    root.write(output_file, format="newick")
    print(f"\nASCII visualization of the {target_genus} Species backbone:")
    print(root.ascii_art())

if __name__ == "__main__":
    # Focuses top-down clustering on the Species within a single genus
    build_top_down_backbone(target_genus="Papilio")
