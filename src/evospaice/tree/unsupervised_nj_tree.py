import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist, squareform
from skbio.tree import nj, TreeNode
from skbio.stats.distance import DistanceMatrix
import faiss
import sys
import os

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
    
    n_sequences = embeddings.shape[0]
    dim = embeddings.shape[1]
    
    # We choose K clusters (e.g., K=1000) to act as our data-driven "pseudo-species" or "centroids"
    # This keeps the NJ step computationally feasible while capturing structure.
    k_clusters = min(2000, n_sequences // 10)
    
    print(f"L2 Normalizing {n_sequences} embeddings...")
    faiss.normalize_L2(embeddings)
    
    print(f"Running FAISS K-Means to find {k_clusters} unsupervised data-driven centroids...")
    kmeans = faiss.Kmeans(dim, k_clusters, niter=20, verbose=True, spherical=True)
    kmeans.train(embeddings)
    
    # Extract the centroids
    centroids = kmeans.centroids
    
    print("Assigning sequences to their nearest centroid...")
    # I returns the cluster index each sequence belongs to
    distances, I = kmeans.index.search(embeddings, 1)
    labels = I.flatten()
    print("1. Building Cluster subtrees (bottom-up) from sequence embeddings...")
    cluster_subtrees = {}
    
    # Group sequences by their cluster
    cluster_to_seq_indices = {}
    for idx, cluster_idx in enumerate(labels):
        if cluster_idx not in cluster_to_seq_indices:
            cluster_to_seq_indices[cluster_idx] = []
        cluster_to_seq_indices[cluster_idx].append(idx)
        
    for cluster_idx, indices in cluster_to_seq_indices.items():
        seq_ids = [ids[i] for i in indices]
        seq_vecs = embeddings[indices]
        
        # Build NJ tree of sequence embeddings inside this cluster
        cl_tree = build_nj_subclade(seq_ids, seq_vecs)
        cluster_subtrees[cluster_idx] = cl_tree
    
    print(f"2. Building Data-Driven Backbone Tree across {k_clusters} unsupervised centroids using NJ...")
    
    # Re-normalize centroids just to be safe before distance matrix
    faiss.normalize_L2(centroids)
    centroid_dists = pdist(centroids, metric='cosine')
    dist_matrix = squareform(centroid_dists)
    
    cluster_names = [f"Cluster_{i}" for i in range(k_clusters)]
    
    print("Constructing DistanceMatrix...")
    dm = DistanceMatrix(dist_matrix, cluster_names)
    
    print("Running Neighbor-Joining (NJ) on backbone...")
    global_tree = nj(dm)
    
    print("3. Grafting individual sequence subtrees onto their data-driven clusters...")
    
    if global_tree.is_tip():
        cluster_idx = int(global_tree.name.split("_")[1])
        cl_node = cluster_subtrees.get(cluster_idx)
        if cl_node:
            global_tree.append(cl_node)
    else:
        for node in list(global_tree.tips()):
            cluster_idx = int(node.name.split("_")[1])
            cl_node = cluster_subtrees.get(cluster_idx)
            if cl_node:
                node.append(cl_node)
            
    print("Fixing missing branch lengths across grafted internal nodes...")
    for node in global_tree.traverse():
        if node.length is None:
            node.length = 0.0

    print("4. Midpoint Rooting complete tree...")
    final_tree = global_tree.root_at_midpoint()
    
    output_file = 'data/unsupervised_nj_tree_midpoint.tre.txt'
    print(f"Writing fully unsupervised bottom-up NJ tree to {output_file}...")
    final_tree.write(output_file, format="newick")
    print("Tree saved successfully.")

if __name__ == "__main__":
    main()
