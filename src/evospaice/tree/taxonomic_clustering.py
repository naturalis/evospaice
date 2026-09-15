import numpy as np
import faiss
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import minimum_spanning_tree
import pandas as pd

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
    
    # We group by species to get a single representative embedding per species
    print("Computing species centroids...")
    
    # Filter out empty or NaN species
    valid_species_mask = (df['species'] != "") & (df['species'].notna()) & (df['species'] != "nan")
    df_valid = df[valid_species_mask]
    
    unique_species = df_valid['species'].unique()
    
    species_list = []
    family_list = []
    genus_list = []
    centroid_embeddings = []
    
    for sp in unique_species:
        sp_indices = df_valid[df_valid['species'] == sp]['idx'].values
        if len(sp_indices) > 0:
            sp_embeddings = embeddings[sp_indices]
            centroid = np.mean(sp_embeddings, axis=0)
            centroid_embeddings.append(centroid)
            
            species_list.append(sp)
            family_list.append(df.iloc[sp_indices[0]]['family'])
            genus_list.append(df.iloc[sp_indices[0]]['genus'])
            
    centroid_embeddings = np.array(centroid_embeddings, dtype=np.float32)
    species_list = np.array(species_list)
    family_list = np.array(family_list)
    genus_list = np.array(genus_list)
    
    print("Performing L2 normalization on centroids...")
    faiss.normalize_L2(centroid_embeddings)
    
    N, dim = centroid_embeddings.shape
    
    print(f"Building HNSW index for {N} species centroids...")
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
    
    print("Exporting MST to edge list...")
    mst_coo = mst.tocoo()
    
    source_idx = mst_coo.row
    target_idx = mst_coo.col
    
    edges_df = pd.DataFrame({
        'Source_Family': family_list[source_idx],
        'Source_Genus': genus_list[source_idx],
        'Source_Species': species_list[source_idx],
        
        'Target_Family': family_list[target_idx],
        'Target_Genus': genus_list[target_idx],
        'Target_Species': species_list[target_idx],
        
        'Distance': mst_coo.data
    })
    
    output_file = 'data/mst_edges_species_centroids.csv'
    edges_df.to_csv(output_file, index=False)
    print(f"Successfully saved {len(edges_df)} species-level tree edges to {output_file}")

if __name__ == "__main__":
    main()
