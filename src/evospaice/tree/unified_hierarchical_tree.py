import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform
from scipy.cluster.hierarchy import linkage, to_tree
from skbio.tree import nj, TreeNode
from skbio.stats.distance import DistanceMatrix
import faiss
import sys
import os

sys.setrecursionlimit(100000)

def sanitize_name(name):
    return str(name).replace(":", "_").replace("(", "_").replace(")", "_").replace(",", "_").replace(";", "_").replace(" ", "_")

def main():
    file_path = 'data/dnabert-s_BOLD_Public.30-Jun-2026-Lepidoptera-BIN-representatives.npz'
    print("Loading data...")
    data = np.load(file_path, allow_pickle=True)
    
    embeddings = data['embeddings'].astype(np.float32)
    ids = data['ids']
    
    family = data['family']
    genus = data['genus']
    species = data['species']
    
    df = pd.DataFrame({
        'id': ids,
        'family': family,
        'genus': genus,
        'species': species,
        'idx': np.arange(len(ids))
    })

    # Filter out missing taxonomic labels
    valid_mask = (df['family'] != "") & (df['family'].notna()) & (df['family'] != "nan") & \
                 (df['genus'] != "") & (df['genus'].notna()) & (df['genus'] != "nan") & \
                 (df['species'] != "") & (df['species'].notna()) & (df['species'] != "nan")
    df_valid = df[valid_mask].copy()

    print("Precomputing centroids for Family, Genus, and Species...")
    
    family_centroids = {}
    genus_centroids = {}
    species_centroids = {}
    
    # Species centroids
    for sp_name, group in df_valid.groupby('species'):
        sp_indices = group['idx'].values
        sp_embeddings = embeddings[sp_indices]
        species_centroids[sp_name] = np.mean(sp_embeddings, axis=0)
        
    sp_names = list(species_centroids.keys())
    sp_matrix = np.array(list(species_centroids.values()), dtype=np.float32)
    faiss.normalize_L2(sp_matrix)
    for i, name in enumerate(sp_names):
        species_centroids[name] = sp_matrix[i]
        
    # Genus centroids
    for gen_name, group in df_valid.groupby('genus'):
        gen_indices = group['idx'].values
        gen_embeddings = embeddings[gen_indices]
        genus_centroids[gen_name] = np.mean(gen_embeddings, axis=0)
        
    gen_names = list(genus_centroids.keys())
    gen_matrix = np.array(list(genus_centroids.values()), dtype=np.float32)
    faiss.normalize_L2(gen_matrix)
    for i, name in enumerate(gen_names):
        genus_centroids[name] = gen_matrix[i]
        
    # Family centroids
    for fam_name, group in df_valid.groupby('family'):
        fam_indices = group['idx'].values
        fam_embeddings = embeddings[fam_indices]
        family_centroids[fam_name] = np.mean(fam_embeddings, axis=0)
        
    fam_names = list(family_centroids.keys())
    fam_matrix = np.array(list(family_centroids.values()), dtype=np.float32)
    faiss.normalize_L2(fam_matrix)
    for i, name in enumerate(fam_names):
        family_centroids[name] = fam_matrix[i]

    print("Building Hard Backbone (Family Level)...")
    fam_dists = pdist(fam_matrix, metric='cosine')
    fam_Z = linkage(fam_dists, method='average')
    
    def build_backbone_tree(node, fam_names):
        if node.is_leaf():
            fam_name = fam_names[node.id]
            t = TreeNode(name=sanitize_name(fam_name))
            t.original_name = fam_name 
            return t
        
        left_tree = build_backbone_tree(node.get_left(), fam_names)
        right_tree = build_backbone_tree(node.get_right(), fam_names)
        
        left_tree.length = max(0.0, node.dist / 2)
        right_tree.length = max(0.0, node.dist / 2)
        
        parent = TreeNode()
        parent.append(left_tree)
        parent.append(right_tree)
        return parent
        
    unified_tree = build_backbone_tree(to_tree(fam_Z), fam_names)
    
    print("Building Genus and Species Levels guided by taxonomy...")
    
    # 1. Attach Genera to Families using NJ
    fam_leaves = list(unified_tree.tips())
    
    for fam_leaf in fam_leaves:
        fam_name = getattr(fam_leaf, 'original_name', None)
        if not fam_name:
            continue
            
        fam_group = df_valid[df_valid['family'] == fam_name]
        fam_genera = fam_group['genus'].unique()
        
        if len(fam_genera) == 0:
            continue
            
        # Attach genera to family
        if len(fam_genera) == 1:
            gen_name = fam_genera[0]
            gen_node = TreeNode(name=sanitize_name(gen_name), length=0.0)
            gen_node.original_name = gen_name
            fam_leaf.append(gen_node)
        else:
            sub_gen_names = list(fam_genera)
            sub_gen_matrix = np.array([genus_centroids[g] for g in sub_gen_names])
            
            sub_dists = pdist(sub_gen_matrix, metric='cosine')
            dist_matrix = squareform(sub_dists)
            sanitized_sub_names = [sanitize_name(n) for n in sub_gen_names]
            dm = DistanceMatrix(dist_matrix, sanitized_sub_names)
            
            try:
                sub_tree = nj(dm)
                for tip in sub_tree.tips():
                    orig_idx = sanitized_sub_names.index(tip.name)
                    tip.original_name = sub_gen_names[orig_idx]
                    
                for child in list(sub_tree.children):
                    fam_leaf.append(child)
            except Exception as e:
                for g in sub_gen_names:
                    gen_node = TreeNode(name=sanitize_name(g), length=0.0)
                    gen_node.original_name = g
                    fam_leaf.append(gen_node)

    # 2. Attach Species to Genera using NJ
    for gen_leaf in list(unified_tree.tips()):
        gen_name = getattr(gen_leaf, 'original_name', None)
        if not gen_name:
            continue
            
        # Check if this leaf is actually a genus (it should be, since we just appended them to family leaves)
        gen_group = df_valid[df_valid['genus'] == gen_name]
        gen_species = gen_group['species'].unique()
        
        if len(gen_species) == 0:
            continue
            
        if len(gen_species) == 1:
            sp_name = gen_species[0]
            sp_node = TreeNode(name=sanitize_name(sp_name), length=0.0)
            sp_node.original_name = sp_name
            gen_leaf.append(sp_node)
        else:
            sub_sp_names = list(gen_species)
            sub_sp_matrix = np.array([species_centroids[sp] for sp in sub_sp_names])
            
            sub_dists = pdist(sub_sp_matrix, metric='cosine')
            dist_matrix = squareform(sub_dists)
            sanitized_sub_names = [sanitize_name(n) for n in sub_sp_names]
            dm = DistanceMatrix(dist_matrix, sanitized_sub_names)
            
            try:
                sub_tree = nj(dm)
                for tip in sub_tree.tips():
                    orig_idx = sanitized_sub_names.index(tip.name)
                    tip.original_name = sub_sp_names[orig_idx]
                    
                for child in list(sub_tree.children):
                    gen_leaf.append(child)
            except Exception as e:
                for sp in sub_sp_names:
                    sp_node = TreeNode(name=sanitize_name(sp), length=0.0)
                    sp_node.original_name = sp
                    gen_leaf.append(sp_node)

    # 3. Graft sequences to Species
    print("Grafting sequences to Species...")
    for sp_leaf in list(unified_tree.tips()):
        sp_name = getattr(sp_leaf, 'original_name', None)
        if not sp_name:
            continue
            
        sp_group = df_valid[df_valid['species'] == sp_name]
        sp_indices = sp_group['idx'].values
        sp_embeddings = embeddings[sp_indices].copy()
        faiss.normalize_L2(sp_embeddings)
        centroid = species_centroids[sp_name]
        
        cos_sims = np.dot(sp_embeddings, centroid)
        cos_dists = np.clip(1.0 - cos_sims, 0, 2)
        sp_ids = sp_group['id'].values
        
        for i, (seq_id, dist) in enumerate(zip(sp_ids, cos_dists)):
            seq_node = TreeNode(name=sanitize_name(seq_id), length=max(0.0, float(dist)))
            sp_leaf.append(seq_node)

    output_file = 'data/unified_taxonomic_tree.tre.txt'
    print(f"Writing unified Newick tree to {output_file}...")
    unified_tree.write(output_file, format="newick")
    
    # Save taxonomy metadata for visualization (e.g. Taxonium)
    metadata_file = 'data/unified_taxonomic_tree_metadata.tsv'
    print(f"Writing metadata to {metadata_file}...")
    df_meta = df_valid[['id', 'family', 'genus', 'species']].copy()
    df_meta['id'] = df_meta['id'].apply(sanitize_name)
    df_meta.to_csv(metadata_file, sep='\t', index=False)
    
    print("Tree and metadata saved successfully.")

if __name__ == "__main__":
    main()
