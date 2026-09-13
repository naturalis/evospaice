# Building the tree from precomputed embeddings

For the recommended cloud services and deployment flow, see the
[Azure Container Apps Jobs tree architecture](azure-container-apps-tree-architecture.md).

## 1. Starting point

This design starts **after embedding has finished**. It assumes that every
retained DNA record has:

- a stable `record_id`;
- a stable `leaf_id` for the tree tip, normally its `bin_uri`;
- one precomputed embedding vector;
- metadata linked to that vector by `record_id`; and
- as much taxonomy as BOLD provides, from kingdom down to species or BIN.

The implementation does not read DNA sequences and does not run the embedding
model. Its job is to turn the vectors and taxonomy into a tree with branch
lengths.

The key scaling rule is:

> Never calculate distances between all records. At one taxonomy node, compare
> only that node's direct children.

## 2. Inputs

Use three required inputs and one optional policy file.

| Input | Required content | Important checks |
| --- | --- | --- |
| `records.tsv` | `leaf_id`, `record_id`, `bin_uri`, and taxonomy columns such as kingdom, phylum, class, order, family, subfamily, tribe, genus, and species | `leaf_id` and `record_id` are unique; rank values are normalised; missing ranks are explicit |
| `embeddings.npy` | A two-dimensional `float32` array with one vector per embedded record | Shape is `(record_count, vector_size)`; all values are finite; no zero-length vectors |
| `embedding-index.tsv` | `record_id` and `row_index` linking each record to one row in `embeddings.npy` | IDs and row indexes are unique; indexes are in range; every retained record has exactly one vector |
| `trust-policy.json` | Optional rules saying which ranks or depths may be resolved and scaled | Use a conservative default for a first candidate tree; use the validated policy for the final tree |

If `records.tsv` already defines the exact row order of `embeddings.npy`, the
separate index file can be omitted. The loader should still create and validate
an explicit `record_id -> row_index` map. It must never rely on two files
happening to have the same order without checking them.

### Leaf identity

The current project tree has one tip per BOLD BIN. Therefore, the input to this
stage should contain one selected record and embedding per BIN:

- `leaf_id` is the stable tree-tip label, normally `bin_uri`;
- `record_id` identifies the original BOLD record whose embedding was selected;
- and
- the manifest keeps the link back to all source and selection details.

If the embedding input contains several records for one BIN, select one within
that BIN before building the tree. Attaching every record as a separate tip
would reintroduce sampling bias and would be a different tree design. Never
deduplicate identical embeddings across different BINs.

### Minimum metadata fields

```text
leaf_id      record_id  bin_uri    kingdom    phylum    class    order    family
subfamily    tribe      genus      species   subspecies
```

Extra BOLD fields and quality flags may be retained. They should be copied to a
sidecar or Newick annotations, not used to change taxonomy silently.

## 3. Outputs

| Output | Purpose |
| --- | --- |
| `scaled-tree.nwk` | Final rooted Newick tree with `leaf_id` values at the tips and finite, non-negative branch lengths |
| `node-diagnostics.tsv` | One row per processed taxonomy node describing child count, method, confidence, fit error, clamped lengths, fallback, runtime, and memory |
| `excluded-records.tsv` | Records that could not be placed, with a clear reason |
| `tree-manifest.json` | Input checksums, configuration, metric, policy version, code version, counts, random seed, and output checksums |
| `checkpoints/` | Completed subtree results that allow a stopped run to resume |

Every tip label in `scaled-tree.nwk` equals its `leaf_id`. The source
`record_id` remains attached as provenance metadata and is not used as the tip
label.

Synthetic nodes created by NJ need stable generated IDs. For example, hash the
parent taxonomy node ID, the sorted child IDs, the algorithm name, and the
configuration version. Stable IDs make reruns and comparisons practical.

## 4. Internal data model

Use compact objects with IDs instead of copying vectors into every tree node.

```python
@dataclass
class TreeNode:
    node_id: str
    label: str
    rank: str
    parent_id: str | None
    child_ids: list[str]
    leaf_id: str | None
    record_id: str | None
    branch_length: float | None
    annotations: dict[str, str]


@dataclass(frozen=True)
class TreeBuildConfig:
    metric: str
    representative: str
    max_nj_children: int
    negative_length_floor: float
    random_seed: int
```

Keep these stores separate:

- `nodes`: `node_id -> TreeNode`;
- `embedding_rows`: `record_id -> row_index`;
- `embeddings`: a memory-mapped NumPy array;
- `representatives`: `node_id -> vector` in memory or a disk-backed store; and
- `diagnostics`: append-only rows written as nodes complete.

For taxonomy nodes, use the full path as identity. A genus name is not always
globally unique, so `(rank, name)` alone is not a safe key. A stable path such
as `kingdom/.../family/genus` prevents unrelated names from merging.

## 5. Suggested package layout

```text
src/evospaice/tree/
  __init__.py
  models.py            TreeNode, configuration, and result types
  inputs.py            Load vectors, index, metadata, and policy
  backbone.py          Build or load the taxonomy tree
  distance.py          Cosine and k-mer distance providers
  representatives.py   Centroid, drift check, and medoid fallback
  resolve.py           NJ and large-group bucketing
  lengths.py           Bottom-up length solve, NNLS fallback, and clamping
  traversal.py         Iterative post-order processing
  output.py            Newick, diagnostics, manifest, and checkpoints
  pipeline.py          End-to-end coordination
```

Keep algorithm code independent of CLI parsing. The CLI should create a
configuration object and call `pipeline.build_tree(...)`.

## 6. Implementation steps

### Step 1 - Load and join by ID

1. Memory-map `embeddings.npy` so the entire matrix does not need to be copied.
2. Read the embedding index and build `record_id -> row_index`.
3. Stream or load the metadata needed for the selected subset.
4. Reject duplicate IDs, duplicate row indexes, missing vectors, extra vectors,
   out-of-range rows, non-finite vectors, and zero-norm vectors.
5. Write every intentional exclusion with a reason.

The result is a validated collection with one leaf per BIN. Each leaf stores
its `leaf_id`, source `record_id`, taxonomy path, and embedding row index.

### Step 2 - Build the taxonomy backbone

Reuse the taxonomy reconciliation rules already implemented in
`evospaice.ingest.tsv2newick`; do not create a second, different interpretation
of BOLD taxonomy inside the tree package.

For every retained record:

1. Read its non-empty ranks in order.
2. Find or create each taxonomy node along that path.
3. Attach a leaf labelled with `leaf_id`, normally the BIN ID.
4. Preserve missing ranks rather than inventing names.
5. Apply the existing conflict policy when a BIN appears in more than one
   lineage, and carry the `lifted` and `suspect` annotations forward.

At this point the tree has the correct taxonomic shape but unresolved
many-child nodes and no useful branch lengths.

### Step 3 - Provide distances on demand

Define one interface that accepts a small matrix of vectors:

```python
class DistanceProvider(Protocol):
    def pairwise(self, vectors: np.ndarray) -> np.ndarray:
        """Return a square distance matrix for only the supplied vectors."""
```

For cosine distance:

1. Receive only the direct-child representatives for the current node.
2. L2-normalise them once when they enter the vector store, or before use.
3. Calculate $D = 1 - VV^T$.
4. Force the diagonal to zero and correct tiny floating-point values below
   zero.
5. Check that the matrix is finite and symmetric.

Do not expose an API that asks for all record pairs. The local-only interface
makes accidental global matrix creation difficult.

### Step 4 - Walk the tree from tips to root

Use an iterative post-order traversal. It avoids Python recursion limits and
makes subtree checkpointing straightforward.

- A leaf's representative is its own embedding vector.
- A taxonomy node is ready only after all direct children are complete.
- A completed node is reduced to one fixed representative for use by its
  parent.

An explicit stack can produce post-order without recursion:

```python
stack = [(root_id, False)]
while stack:
    node_id, visited = stack.pop()
    if visited:
        process_node(node_id)
        continue
    stack.append((node_id, True))
    for child_id in reversed(nodes[node_id].child_ids):
        stack.append((child_id, False))
```

### Step 5 - Process one taxonomy node

For a node with completed direct children:

1. Collect one frozen representative per child.
2. Give every child one vote, regardless of the number of leaves below it.
3. Ask the trust policy whether this rank or depth may be resolved.
4. If there are at least three children and resolution is allowed, calculate
   their local distance matrix and run NJ.
5. Replace the flat set of direct children with the local NJ shape. Graft each
   already-completed child subtree onto the matching NJ leaf.
6. If scaling is allowed at this rank, calculate branch lengths for the
    resulting local shape. Otherwise, use the policy's curated or nominal
    fallback lengths.
7. Calculate and freeze this node's representative.
8. Append one diagnostics row and write a checkpoint when configured.

Nodes with one or two children keep their existing shape. A one-child edge has
no local pairwise evidence, so use the configured fallback length. For two
children, the default is half their pairwise distance on each edge unless the
chosen branch solver or curated backbone provides a better supported split.
Nodes rejected for resolution stay as unresolved bushes; the algorithm must
not force them into a binary tree.

### Step 6 - Protect against very large groups

NJ uses a square distance matrix, so a node with thousands of children can use
too much memory and time. Set `max_nj_children` from measured benchmarks.

When a node exceeds that limit:

1. Cluster its child representatives into about $\sqrt{k}$ groups using a
   deterministic seed.
2. Run NJ separately inside each group.
3. Create one representative for each completed group.
4. Run NJ between the group representatives.
5. Join the group trees under the between-group tree.
6. Check that every original child occurs exactly once.

For the first working version, it is acceptable to leave oversized nodes
unresolved and record `fanout_limit` as the reason. Add bucketing only after the
normal-size path is tested.

### Step 7 - Calculate branch lengths

Implement the Wei and Koslicki bottom-up method behind a `BranchLengthSolver`
interface. Test the solver separately on synthetic trees with known lengths.

For each local tree:

1. Pass the fixed local topology and child-to-child distances to the solver.
2. Calculate edge lengths with the normal bottom-up method.
3. Measure the fit between input distances and path-sum distances in the tree.
4. If the fit exceeds the configured error limit, retry with non-negative least
   squares (NNLS).
5. Change any remaining negative length to zero.
6. Record the solver, fit error, fallback, and number of changed lengths.

NJ may return its own branch lengths, but do not let that bypass the selected
branch-length policy. Treat NJ primarily as the local topology resolver unless
the team explicitly records a decision to use its lengths.

### Step 8 - Create the parent representative

The default representative is the average of the **direct child** vectors:

$$
r_p = \frac{1}{k}\sum_{i=1}^{k} r_i
$$

L2-normalise $r_p$ before cosine comparisons. Equal child weighting prevents a
heavily sampled subtree from dominating its parent.

An average can fall into an unrealistic part of embedding space. Measure the
distance from the average to its nearest child. If that distance exceeds the
validated limit, use the nearest child vector as the medoid fallback. Record
which method was used and never change the representative later in the run.

### Step 9 - Write and verify the tree

Write Newick with a real tree library so quoted BOLD labels and annotations are
not damaged. Before publishing the result, verify that:

- the output parses successfully;
- every included input leaf appears exactly once;
- every excluded leaf has a recorded reason;
- no unexpected leaf was added;
- every branch length is finite and non-negative;
- unresolved nodes remain unresolved where required by policy; and
- all generated internal node IDs are unique and repeatable.

Write the manifest last. A run is complete only after all output checks pass.

## 7. Core orchestration pseudocode

```python
def build_tree(paths: InputPaths, config: TreeBuildConfig) -> BuildResult:
    records = load_metadata(paths.records)
    vectors = open_vector_store(paths.embeddings, paths.embedding_index)
    joined = validate_and_join(records, vectors)
    policy = load_policy(paths.trust_policy, default="candidate")

    tree = build_taxonomy_backbone(joined.records)
    distances = CosineDistanceProvider()
    representatives = RepresentativeStore()
    diagnostics = DiagnosticsWriter(paths.node_diagnostics)

    for node_id in iterative_postorder(tree.root_id):
        node = tree[node_id]

        if node.is_leaf:
            representatives.freeze(node_id, vectors.row_for(node.record_id))
            continue

        child_vectors = representatives.get_many(node.child_ids)
        local_distances = distances.pairwise(child_vectors)
        local_tree = preserve_children(node.child_ids)

        if len(node.child_ids) >= 3 and policy.should_resolve(node):
            local_tree = resolve_children(
                node.child_ids,
                local_distances,
                max_children=config.max_nj_children,
            )

        if policy.should_scale(node):
            length_result = assign_branch_lengths(local_tree, local_distances)
        else:
            length_result = apply_fallback_lengths(local_tree, policy)
        tree.replace_children(node_id, length_result.tree)

        representative = choose_representative(child_vectors, config)
        representatives.freeze(node_id, representative.vector)
        diagnostics.write(node, length_result, representative)

    validate_output_tree(tree, joined)
    write_newick(tree, paths.scaled_tree)
    write_manifest(paths, config, joined, diagnostics.summary())
    return BuildResult(paths.scaled_tree, paths.node_diagnostics)
```

The production code may organise these calls differently, but it should keep
the same boundaries: validated ID join, local distances, one post-order pass,
policy-gated resolution, explicit branch-length solving, and final checks.

### Implemented path

The first complete implementation is in `src/evospaice/tree`. It separates
input adapters, the taxonomy graph, distance and representative strategies,
topology resolution, branch-length fitting, artifact publication, and pipeline
coordination. The supplied mock data can be run without the BOLD export:

```powershell
$env:PYTHONPATH = "src"
python -m evospaice.cli tree `
    --records data/mock-tree/records.tsv `
    --embeddings data/mock-tree/embeddings.tsv `
    --embedding-index data/mock-tree/embedding-index.tsv `
    --trust-policy data/mock-tree/trust-policy.json `
    --output-dir output/mock-tree
```

The mock vectors use reviewable TSV. Production vectors should use a
two-dimensional NumPy `.npy` file, which the loader opens with memory mapping.
The initial implementation leaves nodes above `max_nj_children` unresolved and
records `fanout_limit`; deterministic large-group bucketing remains a scaling
follow-up.

## 8. Recommended implementation order

| Phase | Work | Existing backlog tasks | Exit check |
| --- | --- | --- | --- |
| 1. Contracts and loading | Define files, join vectors to records, validate inputs | ARC-02, ARC-03, TRE-01 | A deliberately broken join fails with a clear error |
| 2. Backbone and traversal | Build/load taxonomy and implement post-order walking | ING-07, ING-08, TRE-02 | Every child is processed before its parent |
| 3. Representatives and distances | Add centroid, medoid fallback, and local cosine matrices | TRE-03 to TRE-05 | No distance outside the current child set is requested |
| 4. Local topology | Run NJ and graft completed child subtrees | TRE-06 | A known small tree recovers the expected split |
| 5. Branch lengths | Add the bottom-up solver, diagnostics, clamping, and NNLS | TRE-07, TRE-08, TRE-11 | A synthetic tree recovers known lengths |
| 6. Complete tree pass | Combine topology and lengths in one traversal | TRE-09, TRE-10 | A test dataset produces a valid policy-gated Newick tree |
| 7. Scale and recovery | Add fan-out handling, checkpoints, and benchmarks | TRE-12 to TRE-15 | Stress runs stay within limits and restart correctly |

Build phases 1 through 6 on a tiny fixture before adding large-node bucketing or
parallel execution. This gives the team a correct end-to-end path early and
keeps performance work from hiding algorithm errors.

## 9. Tests that define correctness

### Unit tests

- ID joins reject duplicates, gaps, extra rows, and non-finite vectors.
- Cosine distance is symmetric, finite, non-negative, and zero on the diagonal.
- Taxonomy paths do not merge same-named taxa under different parents.
- Post-order traversal always completes children before parents.
- Equal-child centroids ignore differences in descendant leaf counts.
- Medoid fallback triggers at the configured drift limit.
- NJ receives only direct-child distances and preserves every child once.
- The branch solver recovers exact synthetic lengths within tolerance.
- Negative lengths are clamped and counted.
- Trust-policy rejection leaves a node unresolved.

### Integration tests

- A small records-plus-embeddings fixture produces the expected tree.
- Input and output leaf sets match after explicit exclusions.
- A run using cosine and a run using k-mers follow the same code path.
- A stopped run resumes from the latest valid subtree checkpoint.
- Two runs with the same inputs, configuration, and seed produce equivalent
  Newick and diagnostics.

### First useful end-to-end test

Use a small family with:

- several genera;
- at least one genus with three or more direct children;
- one record with missing lower-rank taxonomy;
- one suspect or lifted BIN;
- one node that exceeds a deliberately small NJ limit; and
- known synthetic embeddings in addition to a small set of real embeddings.

The synthetic vectors prove that the algorithm is correct. The real vectors
show whether the resulting tree is scientifically plausible. These are
different questions and should remain separate tests.

## 10. First delivery boundary

The first complete implementation is ready when one command can take linked
metadata and precomputed embeddings for a small real subset and produce:

1. a valid `scaled-tree.nwk`;
2. a complete `node-diagnostics.tsv`;
3. an explicit exclusion report;
4. a reproducible manifest; and
5. passing leaf-preservation, branch-length, and deterministic-rerun checks.

Validation may later restrict which nodes are resolved. The first candidate
tree exists to supply that validation evidence; it must not be presented as the
final scientifically approved tree.
