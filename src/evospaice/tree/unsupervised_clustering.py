import numpy as np
import faiss
from scipy.sparse import csr_matrix, coo_matrix
from scipy.sparse.csgraph import minimum_spanning_tree, shortest_path
import pandas as pd
import sys

# Increase recursion depth for deep MST traversal
sys.setrecursionlimit(100000)

def mst_to_newick(mst_matrix, labels):
    """
    Converts a SciPy sparse Minimum Spanning Tree into a Newick string.
    Roots the tree arbitrarily at node 0.
    """
    # Make the tree symmetric (undirected) for traversal
    mst_sym = mst_matrix + mst_matrix.T
    
    n_nodes = mst_sym.shape[0]
    visited = np.zeros(n_nodes, dtype=bool)
    
    # Adjacency list for fast traversal
    coo = mst_sym.tocoo()
    adj_list = {i: [] for i in range(n_nodes)}
    for u, v, w in zip(coo.row, coo.col, coo.data):
        adj_list[u].append((v, w))
        
    def build_newick(node):
        visited[node] = True
        children = []
        for neighbor, weight in adj_list[node]:
            if not visited[neighbor]:
                child_newick = build_newick(neighbor)
                children.append(f"{child_newick}:{weight:.6f}")
                
        if not children:
            return str(labels[node])
        else:
            return f"({','.join(children)}){labels[node]}"
            
    newick_str = build_newick(0) + ";"
    return newick_str

def main():
    file_path = 'data/dnabert-s_BOLD_Public.30-Jun-2026-Lepidoptera-BIN-representatives.npz'
    print("Loading data...")
    data = np.load(file_path, allow_pickle=True)
    
    embeddings = data['embeddings'].astype(np.float32)
    ids = data['ids']
    
    # Extract taxonomy arrays to include in the output
    family = data['family']
    genus = data['genus']
    species = data['species']
    
    print("Performing L2 normalization...")
    faiss.normalize_L2(embeddings)
    
    N, dim = embeddings.shape
    
    print("Building HNSW index (unsupervised)...")
    index = faiss.IndexHNSWFlat(dim, 32)
    index.hnsw.efConstruction = 40
    index.hnsw.efSearch = 16
    index.add(embeddings)
    
    k = 15
    print(f"Querying top {k} neighbors...")
    distances, indices = index.search(embeddings, k)
    distances = np.sqrt(np.maximum(distances, 0))
    
    print("Constructing sparse adjacency matrix...")
    row_ind = np.repeat(np.arange(N), k)
    col_ind = indices.flatten()
    data_val = distances.flatten()
    
    mask = row_ind != col_ind
    row_ind = row_ind[mask]
    col_ind = col_ind[mask]
    data_val = data_val[mask]
    
    adjacency_matrix = csr_matrix((data_val, (row_ind, col_ind)), shape=(N, N))
    
    print("Computing Minimum Spanning Tree (MST)...")
    mst = minimum_spanning_tree(adjacency_matrix)
    
    print("Exporting MST to edge list with taxonomy mapping...")
    mst_coo = mst.tocoo()
    
    # Map the matrix indices back to actual IDs and taxonomy
    source_idx = mst_coo.row
    target_idx = mst_coo.col
    
    edges_df = pd.DataFrame({
        'Source_ID': ids[source_idx],
        'Source_Family': family[source_idx],
        'Source_Genus': genus[source_idx],
        'Source_Species': species[source_idx],
        
        'Target_ID': ids[target_idx],
        'Target_Family': family[target_idx],
        'Target_Genus': genus[target_idx],
        'Target_Species': species[target_idx],
        
        'Distance': mst_coo.data
    })
    
    output_file = 'data/mst_edges_embeddings.csv'
    edges_df.to_csv(output_file, index=False)
    print(f"Successfully saved {len(edges_df)} tree edges to {output_file}")
    
    print("Converting MST to Newick format...")
    newick_str = mst_to_newick(mst, ids)
    newick_file = 'data/mst_embeddings_unsupervised.tre.txt'
    with open(newick_file, 'w') as f:
        f.write(newick_str)
    print(f"Successfully saved Newick tree to {newick_file}")

if __name__ == "__main__":
    main()
