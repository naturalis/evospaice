import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform
from scipy.cluster.hierarchy import linkage, to_tree
from skbio.tree import nj, TreeNode
from skbio.stats.distance import DistanceMatrix
import faiss
import sys

sys.setrecursionlimit(100000)

def sanitize_name(name):
    return str(name).replace(":", "_").replace("(", "_").replace(")", "_").replace(",", "_").replace(";", "_").replace(" ", "_")

def build_small_subtree(target_genus="Papilio", max_species=None):
    """
    Builds a subtree bottom-up by filtering the dataset to a specific Genus,
    and optionally limiting the number of species. If limits are None,
    it takes ALL species for that genus.
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

    # Filter out missing taxonomic labels and isolate the target genus
    valid_mask = (df['genus'] == target_genus) & \
                 (df['species'] != "") & (df['species'].notna()) & (df['species'] != "nan")
    
    df_valid = df[valid_mask].copy()
    
    if len(df_valid) == 0:
        print(f"Error: No data found for genus '{target_genus}'.")
        return

    # Subsample species
    selected_species = df_valid['species'].unique()
    if max_species is not None:
        selected_species = selected_species[:max_species]
        
    df_valid = df_valid[df_valid['species'].isin(selected_species)]

    print(f"Building tree for {target_genus} with {len(df_valid['species'].unique())} species, "
          f"and {len(df_valid)} total sequences.")

    # 1. Compute Centroids
    print("Computing Species Centroids...")
    species_centroids = {}
    for sp_name, group in df_valid.groupby('species'):
        sp_indices = group['idx'].values
        species_centroids[sp_name] = np.mean(embeddings[sp_indices], axis=0)
        
    sp_names = list(species_centroids.keys())
    sp_matrix = np.array(list(species_centroids.values()), dtype=np.float32)
    faiss.normalize_L2(sp_matrix)
    for i, name in enumerate(sp_names):
        species_centroids[name] = sp_matrix[i]

    # 2. Build the root (Genus level) and attach Species via NJ
    print("Building Species level connections (NJ)...")
    gen_root = TreeNode(name=sanitize_name(target_genus))
    gen_root.original_name = target_genus
    
    if len(sp_names) == 1:
        sp_name = sp_names[0]
        sp_node = TreeNode(name=sanitize_name(sp_name), length=0.0)
        sp_node.original_name = sp_name
        gen_root.append(sp_node)
    else:
        sub_dists = pdist(sp_matrix, metric='cosine')
        dist_matrix = squareform(sub_dists)
        sanitized_sub_names = [sanitize_name(n) for n in sp_names]
        dm = DistanceMatrix(dist_matrix, sanitized_sub_names)
        
        try:
            sub_tree = nj(dm)
            
            # Root the unrooted NJ tree using midpoint rooting!
            sub_tree = sub_tree.root_at_midpoint()
            
            for tip in sub_tree.tips():
                orig_idx = sanitized_sub_names.index(tip.name)
                tip.original_name = sp_names[orig_idx]
            for child in list(sub_tree.children):
                gen_root.append(child)
        except Exception as e:
            print("Failed NJ at Species level, appending directly.")
            for sp in sp_names:
                sp_node = TreeNode(name=sanitize_name(sp), length=0.0)
                sp_node.original_name = sp
                gen_root.append(sp_node)

    # 3. Graft Sequences to Species
    print("Grafting Sequences...")
    for sp_leaf in list(gen_root.tips()):
        sp_name = getattr(sp_leaf, 'original_name', None)
        if not sp_name: continue
            
        sp_group = df_valid[df_valid['species'] == sp_name]
        sp_indices = sp_group['idx'].values
        sp_embeddings = embeddings[sp_indices].copy()
        faiss.normalize_L2(sp_embeddings)
        centroid = species_centroids[sp_name]
        
        cos_sims = np.dot(sp_embeddings, centroid)
        cos_dists = np.clip(1.0 - cos_sims, 0, 2)
        sp_ids = sp_group['id'].values
        
        for seq_id, dist in zip(sp_ids, cos_dists):
            seq_node = TreeNode(name=sanitize_name(seq_id), length=max(0.0, float(dist)))
            sp_leaf.append(seq_node)

    # 4. Output
    output_file = f'data/small_subtree_{sanitize_name(target_genus)}.tre.txt'
    print(f"Writing small tree to {output_file}...")
    gen_root.write(output_file, format="newick")
    print("\nASCII visualization of the small subtree:")
    print(gen_root.ascii_art())

if __name__ == "__main__":
    # Passing None to max_species will take ALL species for the genus
    build_small_subtree(target_genus="Papilio", max_species=None)
