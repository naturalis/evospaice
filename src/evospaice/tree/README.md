One post-order walk of the backbone: at each node, resolve the bush with NJ on a small on-demand distance block, assign branch lengths (Wei & Koslicki's bottom-up method), carry one representative up.

## Simple centroid baseline

`centroid.py` implements Strategy 1 from the
[algorithmic literature survey](../../../docs/dna-tree-algorithmic-literature-survey.html)
as an intentionally simple experimental baseline:

1. Load actual encoder NPZ arrays: `ids`, `embeddings`, `order`, `family`,
   `genus`, and `species`, with pickle disabled.
2. By default, filter to the seven butterfly families. Use `--all-families`
   for the entire input dataset, or `--families` for an explicit selection.
   Optionally filter to a fixed set of reference process IDs.
   Incomplete taxonomies are excluded with explicit
   counts. Invalid vectors and duplicate selected IDs are errors.
3. Build species-level NJ trees from cosine distances between record vectors.
4. At genus, family, and order levels, resolve child representative vectors
   with NJ and graft the complete child trees into the resulting connectors.
5. Propagate the arithmetic mean of all descendant **raw stored vectors**.
   Weight child centroids by record counts to reproduce that mean, rather than
   averaging children equally. This matches the survey's simple centroid
   formula; it is not the hackathon brief's sampling-bias correction.

Connectors are midpoint-rooted as an explicit convention, not as inferred
biological ancestry. Negative NJ edges are clamped to zero and counted. Zero
connectors keep the NJ serialization root. No embedding model inference or
cloud compute jobs are needed.

This baseline deliberately does **not** subtract accumulated subtree offsets,
search attachment locations, calibrate distances, or globally refit lengths.
Grafted leaf paths can therefore overcount embedding distances. Its output is
an embedding-derived baseline, not a validated evolutionary tree.

### Run on the matched butterfly records

Download the desired real Lepidoptera embedding NPZ separately, then run:

```bash
uv run python -m evospaice.tree.centroid \
  --embeddings /path/to/omni-dna-20m_Lepidoptera-BIN-representatives.npz \
  --match-ids data/pruned.labels.txt \
  --reference-tree data/pruned.tre.txt \
  --output-dir /tmp/butterfly-centroid
```

### Run on the complete-taxonomy Lepidoptera cohort

Do not restrict families or intersect with reference IDs:

```bash
uv run python -m evospaice.tree.centroid \
  --embeddings /path/to/omni-dna-20m_Lepidoptera-BIN-representatives.npz \
  --all-families \
  --max-children 1800 \
  --nj-backend skbio \
  --output-dir results/lepidoptera-centroid-complete
```

The June 30, 2026 Omni-DNA-20M Leray bundle contains 181,078 records and
136 distinct raw family values, including missing and unclassified labels.
Requiring complete order/family/genus/species labels retains 100,802 records
across 133 family labels; 80,276 incomplete records are excluded. This builds
one connected tree through every selected species, genus, family, and order,
not a collection of independent genus trees. Existing nonmissing unclassified
labels are preserved as supplied, not reinterpreted as established families.

The largest retained group has 1,710 child representatives, so this run needs
a higher local fan-out limit than the butterfly-only example. NJ still uses
local distance matrices, not a global all-record matrix. The optimized `skbio` backend uses scikit-bio's compiled canonical NJ and
diameter-based midpoint rooting instead of Biopython's Python NJ loops and
repeated rerooting at every tip. It runs natively on Apple Silicon CPUs;
no GPU, new distance geometry, or approximate clustering is involved.
The original `biopython` backend remains the default for reproducibility.
Both retain complete child subtrees, record-count-weighted raw centroids,
and explicit negative-edge clamping. One- and two-child cases retain the
existing implementation. Floating-point and tie-breaking differences can
change resolutions of equal or nearly equal NJ scores and midpoint ties;
backend outputs are not guaranteed to be byte-identical.
The report records the family-selection policy and fan-out limit.
It also records backend/version, architecture, and total runtime. Large local
connectors log their elapsed time as they finish.

The output directory must not already exist. The command writes:

- `centroid.nwk`: tree preserving selected process IDs and taxonomic grouping.
- `selected-records.tsv`: the exact cohort and taxonomy used.
- `evaluated-pairs.tsv`: sampled IDs with embedding and inferred path distances.
- `report.json`: input SHA-256, coverage, algorithm choices, diagnostics,
  sampled path errors, and optional reference comparisons.
- `reference-matched.nwk`: the reference tree pruned to the selected IDs, when
  a reference is supplied.

There is no hidden record subsampling. `--max-children` defaults to 512 and
rejects an oversized local problem instead of dropping data. `--pairs`
defaults to 5,000 uniformly sampled unordered pairs, with `--seed 42`.
Pair evaluation is descriptive, not held-out validation, because all selected
records participate in fitting. Per-rank diagnostics identify the first
taxonomic rank at which a sampled pair differs; ranks with no sampled pairs
are reported as `null`.

Reference topology uses the existing unrooted RF comparison helpers with
strict matched IDs. Reference and embedding-derived branch lengths have
different units: use their path correlations as descriptive comparisons,
not raw length errors as biological calibration.

`uv run pytest tests/test_centroid.py` covers filtering, centroid weighting,
zero-distance groups, leaf preservation, fan-out limits, and reproducibility.

## Compare representations within one genus

Use the exact selected-record cohort from the baseline run:

```bash
uv run python -m evospaice.tree.compare_representations \
  --embeddings /path/to/omni-dna-20m_Lepidoptera-BIN-representatives.npz \
  --metadata /path/to/butterfly-centroid/selected-records.tsv \
  --reference /path/to/butterfly-centroid/reference-matched.nwk \
  --genus Papilio \
  --output-dir results/papilio-comparison
```

The output includes a self-contained `index.html`, `comparison.json`, and
Newick files for centroid, medoid, GSC-weighted centroid, Gaussian/Wasserstein,
spherical Frechet mean, and the reference pruned to exactly the same IDs.
Open the HTML directly or through the local viewer server. Select two trees
to compare; changed unrooted splits are colored, record labels can be searched,
and matching leaves are linked. Display-only subtree rotations reduce crossings
without altering topology. Crossings are not an RF score.

Use **Upload Newick for comparison** to add `.nwk`, `.newick`, `.tre`, `.tree`,
or `.txt` files directly in the browser (up to 20 MB and 500,000 nodes).
No file contents are sent to a server. Every displayed original record ID
must occur exactly once; extra tips are pruned automatically, so the full
`data/pruned.tre.txt` can be compared with the existing Papilio cohort.
Duplicate tips, missing cohort IDs, malformed files, and negative/non-finite
lengths produce explicit errors without replacing the selected trees.

The uploaded tree becomes the right-hand selection and is available in both
dropdowns. Its supplied rooting is retained. Pruning collapses unary nodes
while preserving retained pairwise distances. Missing branch lengths allow
topology/RF comparisons but disable branch-length layout and reference-path
correlation. Embedding correlation is unavailable for uploads because the
page does not contain the underlying embedding-distance pairs.

Uploads last for the current tab only. Newick and JSON downloads are generated
from the embedded/current data, including uploads, and work from an exported
standalone HTML without sibling files. `data.defaultComparison` may specify
the initial `left` and `right` method IDs; absent that setting, the page retains
the original centroid-versus-medoid default.

Run the dependency-free browser-logic tests with
`node --test tests/tree_comparison.test.cjs`.

All point methods use the same species-level cosine distances and NJ/grafting
conventions. The medoid minimizes total cosine distance. GSC weights are the
sum of `edge length / descendant count` along each midpoint-rooted leaf path,
normalized to sum to one; a zero-length tree explicitly uses uniform weights.
The spherical mean uses bounded-iteration Riemannian descent with line search
and rejects ambiguous antipodal inputs rather than silently using a centroid.
Its parent connectors still use cosine distance for the point-method comparison.

Gaussian W2 uses raw Euclidean distances at the leaf level and Gaussian W2 at
species connectors, so local topology can differ too. Its unbiased covariance
is represented by an exact low-rank factor; singleton species have zero
covariance. The Bures covariance term uses the nuclear norm of the product of
the two factors, avoiding dense 256-dimensional covariance square roots.
No artificial covariance regularization is added.

W2 lengths and cosine lengths have different units. The page defaults to
topology-only layout and uses independent scales in branch-length mode.
Comparisons report unrooted RF, cosine-distance rank correlation, and reference
path correlation on all leaf pairs. The JSON's optional scalar-aligned stress
is fitted on those same pairs: it is descriptive, not held-out evaluation or
biological calibration. The shared NJ helper retains the original centroid
baseline behavior, including negative-edge clamping and no attachment correction.
