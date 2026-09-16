import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform
from skbio.tree import nj, TreeNode
from skbio.stats.distance import DistanceMatrix
import faiss
import sys

sys.setrecursionlimit(100000)

def sanitize_name(name):
    return str(name).replace(":", "_").replace("(", "_").replace(")", "_").replace(",", "_").replace(";", "_").replace(" ", "_")

def build_nj_subclade(names, matrix):
    """
    Builds an NJ tree for a given set of vectors.
    Returns a single root node or clade containing the topology.
    """
    if len(names) == 1:
        node = TreeNode(name=sanitize_name(names[0]), length=0.0)
        node.original_name = names[0]
        return node

    if len(names) == 2:
        d = float(np.clip(1.0 - np.dot(matrix[0], matrix[1]), 0, 2))
        clade = TreeNode(length=0.0)
        c1 = TreeNode(name=sanitize_name(names[0]), length=max(0.001, d / 2.0))
        c2 = TreeNode(name=sanitize_name(names[1]), length=max(0.001, d / 2.0))
        c1.original_name = names[0]
        c2.original_name = names[1]
        clade.extend([c1, c2])
        return clade

    dists = pdist(matrix, metric='cosine')
    dist_matrix = squareform(dists)
    sanitized_names = [sanitize_name(n) for n in names]
    dm = DistanceMatrix(dist_matrix, sanitized_names)

    try:
        sub_tree = nj(dm)
        for tip in sub_tree.tips():
            orig_idx = sanitized_names.index(tip.name)
            tip.original_name = names[orig_idx]
        return sub_tree
    except Exception as e:
        clade = TreeNode(length=0.0)
        for name in names:
            node = TreeNode(name=sanitize_name(name), length=0.05)
            node.original_name = name
            clade.append(node)
        return clade


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

    valid_mask = (df['family'].astype(str).str.strip() != "") & (df['family'].notna()) & (df['family'] != "nan") & \
                 (df['genus'].astype(str).str.strip() != "") & (df['genus'].notna()) & (df['genus'] != "nan") & \
                 (df['species'].astype(str).str.strip() != "") & (df['species'].notna()) & (df['species'] != "nan")
    df_valid = df[valid_mask].copy()

    # Normalize sequence embeddings for Cosine metric
    faiss.normalize_L2(embeddings)

    # ---------------------------------------------------------
    # STEP 1 (Bottom): Sequences -> Species Subtrees
    # ---------------------------------------------------------
    print("1. Building Species subtrees from sequence embeddings...")
    species_subtrees = {}
    species_centroids = {}

    for sp_name, group in df_valid.groupby('species'):
        seq_indices = group['idx'].values
        seq_ids = group['id'].values
        seq_vecs = embeddings[seq_indices]

        # Centroid for parent-level calculations
        centroid = np.mean(seq_vecs, axis=0, keepdims=True)
        faiss.normalize_L2(centroid)
        species_centroids[sp_name] = centroid[0]

        # Build NJ tree of sequence embeddings inside this species
        sp_tree = build_nj_subclade(list(seq_ids), seq_vecs)
        species_subtrees[sp_name] = sp_tree

    # ---------------------------------------------------------
    # STEP 2: Species -> Genus Subtrees
    # ---------------------------------------------------------
    print("2. Building Genus subtrees from Species centroids...")
    genus_subtrees = {}
    genus_centroids = {}

    for gen_name, group in df_valid.groupby('genus'):
        unique_species = list(group['species'].unique())
        sp_vecs = np.array([species_centroids[sp] for sp in unique_species])

        centroid = np.mean(sp_vecs, axis=0, keepdims=True)
        faiss.normalize_L2(centroid)
        genus_centroids[gen_name] = centroid[0]

        gen_tree = build_nj_subclade(unique_species, sp_vecs)

        # Graft species subtrees onto genus tips
        if gen_tree.is_tip():
            sp_node = species_subtrees[gen_tree.original_name]
            gen_tree.append(sp_node)
        else:
            for tip in list(gen_tree.tips()):
                sp_name = getattr(tip, 'original_name', None)
                if sp_name in species_subtrees:
                    sp_node = species_subtrees[sp_name]
                    tip.append(sp_node)

        genus_subtrees[gen_name] = gen_tree

    # ---------------------------------------------------------
    # STEP 3: Genera -> Family Subtrees
    # ---------------------------------------------------------
    print("3. Building Family subtrees from Genus centroids...")
    family_subtrees = {}
    family_centroids = {}

    for fam_name, group in df_valid.groupby('family'):
        unique_genera = list(group['genus'].unique())
        gen_vecs = np.array([genus_centroids[gen] for gen in unique_genera])

        centroid = np.mean(gen_vecs, axis=0, keepdims=True)
        faiss.normalize_L2(centroid)
        family_centroids[fam_name] = centroid[0]

        fam_tree = build_nj_subclade(unique_genera, gen_vecs)

        # Graft genus subtrees onto family tips
        if fam_tree.is_tip():
            gen_node = genus_subtrees[fam_tree.original_name]
            fam_tree.append(gen_node)
        else:
            for tip in list(fam_tree.tips()):
                gen_name = getattr(tip, 'original_name', None)
                if gen_name in genus_subtrees:
                    gen_node = genus_subtrees[gen_name]
                    tip.append(gen_node)

        family_subtrees[fam_name] = fam_tree

    # ---------------------------------------------------------
    # STEP 4 (Top): Families -> Global Backbone & Rooting
    # ---------------------------------------------------------
    print("4. Building Global Root from Family centroids...")
    unique_families = list(family_centroids.keys())
    fam_vecs = np.array([family_centroids[fam] for fam in unique_families])

    global_tree = build_nj_subclade(unique_families, fam_vecs)

    # Graft family subtrees onto global root tips
    if global_tree.is_tip():
        fam_node = family_subtrees[global_tree.original_name]
        global_tree.append(fam_node)
    else:
        for tip in list(global_tree.tips()):
            fam_name = getattr(tip, 'original_name', None)
            if fam_name in family_subtrees:
                fam_node = family_subtrees[fam_name]
                tip.append(fam_node)

    print("Fixing missing branch lengths across grafted internal nodes...")
    for node in global_tree.traverse():
        if node.length is None:
            node.length = 0.0

    print("5. Midpoint Rooting complete tree...")
    final_tree = global_tree.root_at_midpoint()

    # ---------------------------------------------------------
    # Output Files
    # ---------------------------------------------------------
    output_file = 'data/unified_taxonomic_tree_bottom_up.tre.txt'
    metadata_file = 'data/unified_taxonomic_tree_bottom_up_metadata.tsv'

    print(f"Writing unified bottom-up tree to {output_file}...")
    final_tree.write(output_file, format="newick")

    print(f"Writing metadata to {metadata_file}...")
    df_meta = df_valid[['id', 'family', 'genus', 'species']].copy()
    df_meta['id'] = df_meta['id'].apply(sanitize_name)
    df_meta.to_csv(metadata_file, sep='\t', index=False)

    print("Tree and metadata saved successfully.")

if __name__ == "__main__":
    main()