# Mock tree results

This document explains the output produced from the 100-record mock dataset on
2026-09-13. The same tree was generated locally and by the Azure Container Apps
Job.

## Run summary

| Result | Value |
| --- | ---: |
| Leaves | 100 |
| Total nodes | 188 |
| Processed internal nodes | 38 |
| Excluded records | 0 |
| Distance metric | Cosine distance |
| Policy version | `mock-v1` |
| Manifest status | `complete` |

The successful Azure execution was `evospaice-tree-build-hionvg4`. Its output
was written below this immutable Blob Storage prefix:

```text
tree-runs/runs/local/outputs/20260913T175545Z-145b4e03-100tip/
```

## Output files

### `scaled-tree.nwk`

The [scaled tree](../output/mock-tree/scaled-tree.nwk) is the generated rooted
tree in Newick format. It contains:

- 100 terminal leaves, one for each `leaf_id` and BOLD BIN;
- 88 internal nodes;
- 188 nodes in total; and
- 187 branch lengths, one for every non-root node.

Values following a colon are branch lengths. For example:

```text
'BOLD:MOCK002':0.00137725263251
```

The branch length is in embedding-derived cosine-distance units. It is not a
calibrated evolutionary time or a number of nucleotide substitutions per site.

Of the 187 branch lengths, 157 are positive and 30 are zero. A zero length is
valid here. It can be produced by the non-negative fit when an edge is not
needed to represent the observed distances, or by the configured `0.0`
fallback for a one-child taxonomy node.

Positive branch-length statistics are:

| Statistic | Value |
| --- | ---: |
| Minimum | 0.0000352754500955 |
| Maximum | 0.505141197484 |
| Mean | 0.0655414937527146 |
| Median | 0.0013268881346 |

### `node-diagnostics.tsv`

The [node diagnostics](../output/mock-tree/node-diagnostics.tsv) contain one row
for each of the 38 processed taxonomy nodes.

| Column | Meaning |
| --- | --- |
| `node_id` | Stable identifier of the processed taxonomy node |
| `rank` | Taxonomic rank of the node |
| `child_count` | Number of direct children compared locally |
| `topology_method` | Whether Neighbor Joining resolved the children or their topology was preserved |
| `length_method` | Method used to assign local branch lengths |
| `representative_method` | Whether the subtree was represented by a centroid or medoid |
| `fit_error` | RMSE between observed cosine distances and fitted tree-path distances |
| `clamped_lengths` | Number of negative lengths changed to zero |
| `distance_matrix_size` | Number of cells in the local square distance matrix |
| `note` | Additional reason, such as `policy_preserved` |

The diagnostic methods break down as follows:

| Diagnostic | Counts |
| --- | --- |
| Topology | 25 `neighbor_joining`, 13 `preserved` |
| Branch lengths | 31 `nnls`, 2 `two_child_split`, 5 `fallback` |
| Representative | 37 `centroid`, 1 `medoid` |
| Notes | 6 `policy_preserved`, 32 blank |

The trust policy permits topology resolution only at genus rank but permits
distance scaling at every rank. Consequently, all 25 genus nodes were resolved
with Neighbor Joining. Higher taxonomy levels kept their input topology while
still receiving fitted branch lengths.

Genus-level fit errors were small: from approximately `0.000000235` to
`0.000199`. Family-level errors ranged from approximately `0.0167` to `0.0303`.
No branch lengths required post-fit clamping.

### `excluded-records.tsv`

The [excluded-records report](../output/mock-tree/excluded-records.tsv) contains
the columns `leaf_id`, `record_id`, and `reason`. It has no data rows, which
means all 100 validated input records were placed in the tree.

### `tree-manifest.json`

The [tree manifest](../output/mock-tree/tree-manifest.json) is the
reproducibility and integrity record. It contains:

- schema and completion status;
- policy version and tree-building configuration;
- leaf, node, and processed-node counts;
- SHA-256 hashes of every input and primary output;
- the configured distance metric and random seed; and
- evidence that only local distance matrices were constructed.

The manifest reports a largest local child count of 5 and therefore a largest
local matrix of 25 cells. It explicitly reports that no global distance matrix
was created.

### `checkpoints/complete.json`

The [completion checkpoint](../output/mock-tree/checkpoints/complete.json) is a
small marker that records:

```json
{
  "status": "complete",
  "processed_nodes": 38
}
```

The current implementation writes this final marker after processing. It does
not yet contain individual resumable subtree checkpoints.

## Distances

Distances are present in the result in two forms.

### Input cosine distances

For two embedding vectors $x$ and $y$, the application calculates:

$$
d(x,y)=1-\frac{x\cdot y}{\lVert x\rVert\lVert y\rVert}
$$

These distances are calculated only between the direct children of the node
currently being processed. The local matrix sizes in this run were:

| Matrix cells | Child dimensions | Number of matrices |
| ---: | ---: | ---: |
| 1 | $1 \times 1$ | 5 |
| 4 | $2 \times 2$ | 2 |
| 9 | $3 \times 3$ | 1 |
| 16 | $4 \times 4$ | 25 |
| 25 | $5 \times 5$ | 5 |

The total number of local matrix cells is:

$$
5(1) + 2(4) + 1(9) + 25(16) + 5(25) = 547
$$

After excluding diagonal and mirrored cells, the number of unique child-pair
distance calculations is:

$$
5(0) + 2(1) + 1(3) + 25(6) + 5(10) = 205
$$

The application never constructed a global $100 \times 100$ matrix.

The raw local matrices are temporary. They are not stored in an output file.
The diagnostics retain their sizes and fitting errors instead.

### Tree or patristic distances

The fitted distances are persisted as branch lengths in `scaled-tree.nwk`. The
distance between two leaves is the sum of all branch lengths on the path between
them. This is the patristic distance.

Across all 4,950 possible leaf pairs:

| Statistic | Patristic distance |
| --- | ---: |
| Minimum | 0.002199069437464 |
| Maximum | 2.53319691474883 |
| Mean | 1.74832307062368 |
| Median | 1.62041909011363 |

Example comparisons from this run are:

| Relationship | Leaves | Embedding cosine distance | Tree distance |
| --- | --- | ---: | ---: |
| Same genus, `Vanessa` | `BOLD:MOCK001`, `BOLD:MOCK002` | 0.003012 | 0.002667 |
| Different genera in `Nymphalidae` | `BOLD:MOCK001`, `BOLD:MOCK009` | 0.566165 | 0.576672 |
| Different families | `BOLD:MOCK001`, `BOLD:MOCK005` | 0.945520 | 2.487206 |

The tree distance is not expected to equal the direct cosine distance exactly.
The branch solver fits many observed local distances to a shared tree topology,
and the path between distant leaves crosses branch lengths fitted independently
at several taxonomy levels.

## Interpretation limits

The mock embedding vectors are deterministic synthetic data shaped like
Omni-DNA-20M output vectors. They were not produced by model inference from real
DNA sequences. This result demonstrates that the pipeline preserves leaves,
builds policy-controlled topology, computes local distances, fits non-negative
branch lengths, and publishes reproducible artifacts. It is not evidence that
the resulting relationships are biologically or evolutionarily valid.

There is currently no standalone leaf-by-leaf distance table or raw distance
matrix artifact. Those values can be derived from the embeddings or from the
Newick branch lengths if a downstream analysis requires them.