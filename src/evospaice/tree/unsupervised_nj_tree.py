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
    cos_dists = np.clip(1.0 - (1.0 - distances.flatten()/2), 0, 2) # faiss spherical kmeans search returns L2 dist^2.
    
    # Actually, spherical kmeans search returns L2 distance squared between L2 normalized vectors.
    # L2^2 = 2 - 2*cos_sim => cos_dist = 1 - cos_sim = L2^2 / 2
    cos_dists = np.clip(distances.flatten() / 2.0, 0, 2)
    
    print(f"Building Data-Driven Backbone Tree across {k_clusters} unsupervised centroids using NJ...")
    
    # Re-normalize centroids just to be safe before distance matrix
    faiss.normalize_L2(centroids)
    centroid_dists = pdist(centroids, metric='cosine')
    dist_matrix = squareform(centroid_dists)
    
    cluster_names = [f"Cluster_{i}" for i in range(k_clusters)]
    
    print("Constructing DistanceMatrix...")
    dm = DistanceMatrix(dist_matrix, cluster_names)
    
    print("Running Neighbor-Joining (NJ)...")
    tree = nj(dm)
    
    print("Grafting individual sequence leaves onto their data-driven clusters...")
    
    # Group sequences by their cluster
    cluster_to_seqs = {}
    for idx, (seq_id, cluster_idx, dist) in enumerate(zip(ids, labels, cos_dists)):
        if cluster_idx not in cluster_to_seqs:
            cluster_to_seqs[cluster_idx] = []
        cluster_to_seqs[cluster_idx].append((seq_id, dist))
        
    for node in tree.tips():
        cluster_idx = int(node.name.split("_")[1])
        seqs = cluster_to_seqs.get(cluster_idx, [])
        
        for seq_id, dist in seqs:
            safe_seq_id = sanitize_name(seq_id)
            child = TreeNode(name=safe_seq_id, length=max(0.0, float(dist)))
            node.append(child)
            
    output_file = 'data/unsupervised_nj_tree.tre.txt'
    print(f"Writing fully unsupervised NJ tree to {output_file}...")
    tree.write(output_file, format="newick")
    print("Tree saved successfully.")

if __name__ == "__main__":
    main()
