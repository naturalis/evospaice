# Omni-DNA embedding model

## Model

The pipeline uses the public `zehui127/Omni-DNA-20M` checkpoint from Hugging
Face. The checkpoint is MIT licensed and uses custom Transformers model code.
The validated production revision is:

```text
3b64e6a5ed6c8f72bad76823ce728b3045243026
```

The model is an autoregressive genomic transformer with a 256-dimensional hidden
state. It runs on the dedicated `Standard_NC24ads_A100_v4` AML compute cluster.

## Input processing

- FASTA sequences are uppercased and line breaks are removed.
- Records are processed in batches, currently 256 records per batch.
- Tokenization adds model special tokens.
- Inputs are truncated to at most 1,024 tokenizer tokens.
- Padding is masked during pooling.

The 1,024-token setting matches the previously validated Omni-DNA encoder used in
the AML workspace. It represents tokenizer length, not nucleotide count.

## Pooling

For each sequence:

1. Run the causal model with final hidden states enabled.
2. Select the final transformer hidden state.
3. Compute the attention-mask-weighted mean across tokens.
4. Convert to float32.
5. L2-normalize the 256-dimensional vector.

For token vectors $h_i$ and attention mask $m_i$, pooling is:

$$
v = \frac{\sum_i m_i h_i}{\max(1, \sum_i m_i)}
$$

The vector stored in FAISS is:

$$
\hat{v} = \frac{v}{\lVert v \rVert_2}
$$

Because vectors are normalized, `IndexFlatIP` inner product equals cosine
similarity.

## Reproducibility

Each global manifest records:

- model identifier
- resolved model revision
- maximum token length
- pooling method
- vector dimension
- normalization flag
- source blob URL, ETag, and size
- index and metadata SHA-256 checksums

The AML job uses a known workspace environment and installs only missing runtime
packages. Production should pin the model revision explicitly before treating
newly generated embeddings as interchangeable with an existing index.

## Interpretation limits

The embeddings were optimized for genomic representation and retrieval. Nearest
neighbor quality does not by itself prove that cosine distance is additive or
calibrated as evolutionary distance. Downstream tree construction must validate
depth faithfulness, additivity, and tip compression against trusted references
and a k-mer baseline.
