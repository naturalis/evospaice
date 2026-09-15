import numpy as np

file_path = 'data/dnabert-s_BOLD_Public.30-Jun-2026-Lepidoptera-BIN-representatives.npz'
data = np.load(file_path, allow_pickle=True)

# Function to get unique counts excluding empty strings/nan/None if needed
def count_unique(arr):
    # filter out empty strings and None-like values if any
    valid_arr = [str(x) for x in arr if x is not None and str(x).strip() != '']
    unique_items = set(valid_arr)
    return len(unique_items)

family_count = count_unique(data['family'])
genus_count = count_unique(data['genus'])
species_count = count_unique(data['species'])

print(f"Unique Families: {family_count}")
print(f"Unique Genus: {genus_count}")
print(f"Unique Species: {species_count}")

