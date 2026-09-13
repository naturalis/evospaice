# Mock tree-building inputs

This deterministic six-tip dataset exercises the post-embedding tree builder
without requiring the BOLD export or DNABERT-S embeddings.

- `records.tsv` links each mock BIN tip to one source record and taxonomy path.
- `embedding-index.tsv` links record IDs to vector rows.
- `embeddings.tsv` is a human-readable stand-in for production `embeddings.npy`.
- `trust-policy.json` permits local NJ resolution at genus nodes and branch
  scaling at every rank.

Run it from the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m evospaice.cli tree `
  --records data/mock-tree/records.tsv `
  --embeddings data/mock-tree/embeddings.tsv `
  --embedding-index data/mock-tree/embedding-index.tsv `
  --trust-policy data/mock-tree/trust-policy.json `
  --output-dir output/mock-tree
```

Production input should use a two-dimensional `float32` NumPy `.npy` file.
The TSV vector adapter exists so the small fixture remains reviewable in Git.
