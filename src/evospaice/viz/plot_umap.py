import numpy as np
import umap
import matplotlib.pyplot as plt
import argparse

def main():
    parser = argparse.ArgumentParser(description="Plot UMAP of embeddings")
    parser.add_argument("--input", "-i", type=str, default="data/omni-dna-20m_BOLD_Public.30-Jun-2026-Lepidoptera-BIN-representatives.npz")
    parser.add_argument("--output", "-o", type=str, default="images/umap_lepidoptera.png")
    parser.add_argument("--lda", action="store_true", help="Apply supervised Linear Discriminant Analysis before UMAP")
    args = parser.parse_args()

    print(f"Loading data from {args.input}...")
    data = np.load(args.input)
    embeddings = data['embeddings']
    families = data['family']
    
    print(f"Embeddings shape: {embeddings.shape}")
    
    if args.lda:
        print("Running Supervised LDA projection...")
        from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
        # The number of components cannot exceed number of classes - 1.
        # For a large number of families, we cap it at 50 to keep the space compact.
        n_components = min(50, len(np.unique(families)) - 1)
        lda = LinearDiscriminantAnalysis(n_components=n_components)
        embeddings = lda.fit_transform(embeddings, families)
        print(f"LDA Projected shape: {embeddings.shape}")
    
    print("Computing UMAP...")
    reducer = umap.UMAP(n_neighbors=50, metric='cosine', min_dist=0.1, n_components=2, random_state=42)
    embedding_2d = reducer.fit_transform(embeddings)
    
    print("Plotting...")
    # Increase figure size and set background to white
    plt.figure(figsize=(16, 12), facecolor='white')
    
    # Plot all data, colored by top families to see global family relationships
    unique_families = np.unique(families)
    family_counts = {f: np.sum(families == f) for f in unique_families}
    top_families = sorted(family_counts.keys(), key=lambda x: family_counts[x], reverse=True)[:20]
    
    print(f"Plotting top {len(top_families)} families globally...")
    
    other_idx = ~np.isin(families, top_families)
    if np.any(other_idx):
        plt.scatter(embedding_2d[other_idx, 0], embedding_2d[other_idx, 1], label='Other', s=4.0, alpha=0.1, color='#e0e0e0', edgecolors='none')
        
    cmap = plt.get_cmap("tab20")
    for i, family in enumerate(top_families):
        idx = families == family
        plt.scatter(embedding_2d[idx, 0], embedding_2d[idx, 1], label=family, s=4.0, alpha=0.7, color=cmap(i % 20), edgecolors='none')
        
    plt.axis('off')
    
    legend = plt.legend(bbox_to_anchor=(1.02, 1), loc='upper left', markerscale=5, frameon=False, title="Top Families", fontsize=12)
    if legend:
        for handle in legend.legend_handles:
            handle.set_alpha(1.0)

    plt.title("UMAP projection of Lepidoptera (Family level)", fontsize=18, pad=20)
    plt.tight_layout()
    
    print(f"Saving to {args.output}...")
    plt.savefig(args.output, dpi=300, bbox_inches='tight')
    print("Done!")

if __name__ == "__main__":
    main()
