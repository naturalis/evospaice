# Add scalable tree building, Azure execution, and static visualization

## Summary

This PR adds the post-embedding Evospaice pipeline for building a scaled
phylogenetic reference tree.

It:

- builds a taxonomy-backed tree from record metadata;
- resolves permitted local polytomies with Neighbor Joining;
- assigns non-negative branch lengths from cosine embedding distances;
- records diagnostics, configuration, checksums, and completion state;
- supports local execution and Azure Container Apps Jobs;
- renders generated Newick trees as static PNG images; and
- includes a deterministic 100-tip fixture for development and review.

The pipeline computes distance matrices only for the children of the node being
processed. It does not create a global all-pairs distance matrix.

## Inputs

### `records.tsv`

Tab-separated metadata with one selected record per output leaf.

| Column | Meaning |
| --- | --- |
| `leaf_id` | Required unique identifier used as the terminal label in the output tree. |
| `record_id` | Required unique source-record identifier. Joins metadata to the embedding index. |
| `bin_uri` | Required column containing the associated BOLD BIN identifier. |
| `kingdom` | Optional kingdom name. |
| `phylum` | Optional phylum name. |
| `class` | Optional class name. |
| `order` | Optional order name. |
| `family` | Optional family name. |
| `subfamily` | Optional subfamily name. |
| `tribe` | Optional tribe name. |
| `genus` | Optional genus name. |
| `species` | Optional species name. |
| `subspecies` | Optional subspecies name. |

Each record must contain at least one non-empty taxonomy rank. Taxonomy columns
may be omitted below the deepest known rank.

### `embeddings.npy` or `embeddings.tsv`

A two-dimensional embedding matrix with one vector per selected record.

- Production input should be a headerless NumPy `.npy` array, preferably
  `float32`.
- The inspectable mock fixture uses a headerless tab-separated matrix.
- Rows are connected to records through `embedding-index.tsv`.
- All vectors must be finite and non-zero.
- Every row must have the same embedding dimension.

### `embedding-index.tsv`

Optional for local execution and required for cloud execution.

| Column | Meaning |
| --- | --- |
| `record_id` | Record identifier matching exactly one row in `records.tsv`. |
| `row_index` | Zero-based row number in the embedding matrix. |

Record IDs and row indexes must be unique. The index must cover every record and
every embedding row exactly once. If omitted locally, record order in
`records.tsv` is assumed to match embedding row order.

### `trust-policy.json`

Optional for local execution and required for cloud execution.

```json
{
  "version": "mock-v1",
  "resolve_ranks": ["genus"],
  "scale_ranks": ["*"]
}
```

| Field | Meaning |
| --- | --- |
| `version` | Policy identifier recorded in the output manifest. |
| `resolve_ranks` | Taxonomic ranks at which polytomies may be resolved with Neighbor Joining. |
| `scale_ranks` | Ranks at which embedding distances may be used to fit branch lengths. |
| `"*"` | Allows the operation at every rank. |

Without a policy file, the defaults resolve `genus` and `species` nodes and
permit scaling at all ranks.

## Run locally

Install the locked dependencies:

```bash
uv sync --locked --extra azure --extra viz
```

Run the committed 100-tip fixture:

```bash
uv run evospaice tree \
  --records data/mock-tree/records.tsv \
  --embeddings data/mock-tree/embeddings.tsv \
  --embedding-index data/mock-tree/embedding-index.tsv \
  --trust-policy data/mock-tree/trust-policy.json \
  --output-dir output/mock-tree
```

Relevant optional settings are:

| Option | Default | Meaning |
| --- | ---: | --- |
| `--max-nj-children` | `256` | Maximum child count accepted by a local NJ operation. |
| `--centroid-drift-limit` | `0.35` | Maximum permitted representative-centroid drift. |
| `--fallback-branch-length` | `0.0` | Branch length used when fitting is not permitted or possible. |
| `--seed` | `42` | Random seed recorded for reproducibility. |

## Run in Azure

Deploy the resources in `infra/main.bicep`, publish the Docker image to the
provisioned registry, and place these objects under the configured input prefix:

```text
records.tsv
embeddings.npy
embedding-index.tsv
trust-policy.json
```

The Container Apps Job uses managed identity to download the inputs, run the
same pipeline as the local CLI, and upload its artifacts. Start it with:

```bash
az containerapp job start \
  --name <job-name> \
  --resource-group <resource-group>
```

Use a new output prefix when changing inputs or settings. Existing artifacts are
only reused when their SHA-256 metadata matches; conflicting output objects are
not overwritten.

## Outputs

### `scaled-tree.nwk`

The resolved Newick tree. Every non-root edge has a finite, non-negative branch
length based on embedding distance. The scale represents embedding distance,
not evolutionary time or substitutions per site.

### `node-diagnostics.tsv`

One row per processed internal node.

| Column | Meaning |
| --- | --- |
| `node_id` | Stable internal node identifier. |
| `rank` | Taxonomic rank represented by the node. |
| `child_count` | Number of children processed at the node. |
| `topology_method` | How topology was handled, such as `neighbor_joining` or `preserved`. |
| `length_method` | Branch-length method, such as `nnls` or `fallback`. |
| `representative_method` | Method used to carry a representative upward. |
| `fit_error` | Error from the local branch-length fit. |
| `clamped_lengths` | Number of fitted negative lengths clamped to zero. |
| `distance_matrix_size` | Number of elements in the local distance matrix. |
| `note` | Optional diagnostic explanation or fallback detail. |

### `excluded-records.tsv`

Records excluded from the published tree.

| Column | Meaning |
| --- | --- |
| `leaf_id` | Excluded leaf identifier. |
| `record_id` | Excluded source-record identifier. |
| `reason` | Reason the record was excluded. |

The current validated fixture produces a header-only file because all records
are accepted.

### `tree-manifest.json`

The publication manifest containing:

- schema, run, and policy versions;
- effective algorithm configuration;
- leaf, node, and processed-node counts;
- evidence that no global distance matrix was created;
- largest local child and matrix sizes; and
- SHA-256 checksums for every input and primary output.

### `checkpoints/complete.json`

Completion marker containing the final status and processed internal-node count.
In cloud mode this is uploaded after data artifacts and before the manifest.

## Visualize the result

Install the visualization dependency and render the generated tree:

```bash
uv run evospaice viz \
  --tree output/mock-tree/scaled-tree.nwk \
  --output output/mock-tree/scaled-tree.png \
  --show-branch-lengths
```

Useful options:

- `--title "..."` changes the figure title.
- `--show-branch-lengths` annotates fitted edge lengths.
- `--show-internal-labels` displays taxonomy-node labels for diagnostics.

The renderer produces a static PNG with embedding distance on the horizontal
axis. For very large production trees, render a selected clade or use a
large-tree viewer such as iTOL rather than attempting to draw every tip in one
figure.

## Testing

The implementation includes unit and end-to-end coverage for the tree
components, pipeline, cloud adapter, and visualization:

```bash
uv run pytest
```