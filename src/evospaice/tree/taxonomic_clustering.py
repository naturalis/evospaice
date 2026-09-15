import numpy as np
import faiss
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import minimum_spanning_tree
import pandas as pd
import argparse
import sys

sys.setrecursionlimit(100000)

def mst_to_newick(mst_matrix, labels):
    mst_sym = mst_matrix + mst_matrix.T
    n_nodes = mst_sym.shape[0]
    visited = np.zeros(n_nodes, dtype=bool)
    
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
            
    return build_newick(0) + ";"

def main():
    parser = argparse.ArgumentParser(description="Taxonomic Clustering Tree")
    parser.add_argument('--rank', type=str, default='species', choices=['species', 'genus', 'family'], help='Taxonomic rank to cluster by')
    args = parser.parse_args()
    
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

    print(f"Precomputing centroids for rank: {args.rank}...")
    centroids_dict = {}
    r = args.rank
    valid_mask = (df[r] != "") & (df[r].notna()) & (df[r] != "nan")
    df_valid = df[valid_mask]
    c_dict = {}
    grouped = df_valid.groupby(r)
    for name, group in grouped:
        sp_indices = group['idx'].values
        sp_embeddings = embeddings[sp_indices]
        centroid = np.mean(sp_embeddings, axis=0)
        c_dict[name] = centroid
    
    names = list(c_dict.keys())
    matrix = np.array(list(c_dict.values()), dtype=np.float32)
    faiss.normalize_L2(matrix)
    centroids_dict[r] = {names[i]: matrix[i] for i in range(len(names))}

    def get_dist(n1, n2, rank):
        if pd.isna(n1) or pd.isna(n2) or n1 == "" or n2 == "":
            return np.nan
        c1 = centroids_dict[rank].get(n1)
        c2 = centroids_dict[rank].get(n2)
        if c1 is None or c2 is None:
            return np.nan
        return float(np.linalg.norm(c1 - c2))
    
    rank = args.rank
    print(f"\nComputing {rank} centroids network...")
    
    id_list = []
    centroid_embeddings = []
    rank_list = []
    family_list = []
    genus_list = []
    species_list = []
    
    for name, group in grouped:
        sp_indices = group['idx'].values
        sp_embeddings = embeddings[sp_indices]
        centroid = np.mean(sp_embeddings, axis=0)
        
        centroid_embeddings.append(centroid)
        id_list.append(group.iloc[0]['id'])
        rank_list.append(name)
        family_list.append(group.iloc[0]['family'])
        genus_list.append(group.iloc[0]['genus'] if rank != 'family' else "")
        species_list.append(group.iloc[0]['species'] if rank == 'species' else "")
        
    centroid_embeddings = np.array(centroid_embeddings, dtype=np.float32)
    id_list = np.array(id_list)
    rank_list = np.array(rank_list)
    family_list = np.array(family_list)
    genus_list = np.array(genus_list)
    species_list = np.array(species_list)
    
    print("Performing L2 normalization on centroids...")
    faiss.normalize_L2(centroid_embeddings)
    
    N, dim = centroid_embeddings.shape
    
    print(f"Building HNSW index for {N} {rank} centroids...")
    index = faiss.IndexHNSWFlat(dim, 32)
    index.hnsw.efConstruction = 40
    index.hnsw.efSearch = 16
    index.add(centroid_embeddings)
    
    k = min(15, N)
    print(f"Querying top {k} neighbors...")
    distances, indices = index.search(centroid_embeddings, k)
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
    
    mst_coo = mst.tocoo()
    
    source_idx = mst_coo.row
    target_idx = mst_coo.col
    
    edges_df = pd.DataFrame({
        'Rank': rank,
        'Source_ID': id_list[source_idx],
        'Source_Family': family_list[source_idx],
        'Source_Genus': genus_list[source_idx],
        'Source_Species': species_list[source_idx],
        'Source_Rank_Name': rank_list[source_idx],
        
        'Target_ID': id_list[target_idx],
        'Target_Family': family_list[target_idx],
        'Target_Genus': genus_list[target_idx],
        'Target_Species': species_list[target_idx],
        'Target_Rank_Name': rank_list[target_idx],
        
        'Distance': mst_coo.data
    })

    # Calculate distances
    if rank == 'species':
        edges_df['Species_Centroid_Distance'] = edges_df.apply(
            lambda row: get_dist(row['Source_Species'], row['Target_Species'], 'species'), axis=1
        )
    if rank in ['species', 'genus']:
        edges_df['Genus_Centroid_Distance'] = edges_df.apply(
            lambda row: get_dist(row['Source_Genus'], row['Target_Genus'], 'genus') if rank == 'genus' else np.nan, axis=1
        )
    edges_df['Family_Centroid_Distance'] = edges_df.apply(
        lambda row: get_dist(row['Source_Family'], row['Target_Family'], 'family') if rank == 'family' else np.nan, axis=1
    )

    print(f"Successfully processed {len(edges_df)} {rank}-level tree edges.")

    output_file = f'data/mst_edges_{rank}_centroids.csv'
    edges_df.to_csv(output_file, index=False)
    print(f"\nSuccessfully saved {len(edges_df)} edges to {output_file}")
    
    print("Converting MST to Newick format...")
    newick_str = mst_to_newick(mst, id_list)
    newick_file = f'data/mst_{rank}_centroids.tre.txt'
    with open(newick_file, 'w') as f:
        f.write(newick_str)
    print(f"Successfully saved Newick tree to {newick_file}")

if __name__ == "__main__":
    main()
