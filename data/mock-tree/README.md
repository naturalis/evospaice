# Mock tree-building inputs

This deterministic 100-tip dataset exercises the post-embedding tree builder
without requiring the BOLD export or running Omni-DNA-20M inference.

- `records.tsv` links each of 100 mock BIN tips to one source record and taxonomy path.
- `embedding-index.tsv` links record IDs to vector rows.
- `embeddings.tsv` contains deterministic, dense 256-dimensional mock vectors,
  matching Omni-DNA-20M's `d_model`. They preserve taxonomy-like cosine
  clustering but are synthetic and are not model-generated embeddings.
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

Production input should use model-generated vectors in a two-dimensional
`float32` NumPy `.npy` file. The TSV vector adapter keeps this fixture directly
inspectable in Git.
