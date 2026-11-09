One post-order walk of the backbone: at each node, resolve the bush with NJ on a
local on-demand distance block, assign branch lengths, and carry one
representative up. All five survey representations build one connected tree
through **species, genus, family, order, and the common root**.

The standalone scripts added separately on `main` remain available:
[unified bottom-up construction](README_bottom_up.md),
[unsupervised NJ construction](README_unsupervised_nj.md), and
[subtree extraction](README_small_subtree.md). The configurable five-method
CLI and explorers described below use `centroid.py` and `representations.py`;
they do not replace those scripts or their rooting conventions.

## Live localhost merging lab

```bash
uv run evospaice tree live
# Open http://127.0.0.1:8765/
```

The default source is the verified **5,000 × 256 butterfly subset** at
`butterfly-5000-seed42-20260917T081501Z` in the existing private Azure embedding
prefix. Start with the existing authenticated `az login` identity, with Storage
Blob Data Reader permissions. The configured subscription is
`caeead51-e874-4122-ba0e-c3c601c862ca`. Override the source only on the server:

```bash
uv run evospaice tree live --port 8765 \
  --azure-prefix https://ACCOUNT.blob.core.windows.net/CONTAINER/PATH/TO/SUBSET/ \
  --subscription SUBSCRIPTION_ID --expect-records 5000
```

`--port 0` selects an available port and prints its URL. Startup loads the source
but computes **no trees**. Choose the complete cohort or search full taxonomy
paths for an order, family, genus, or species, select one to five representations,
and click **Run merges**. Only those methods are rebuilt, using all selected
descendants and the requested NJ backend. This is a fresh build, **not** an
induced/pruned view of a precomputed full tree. Higher ancestors are unary
context above the selected scope. All selected methods use the same records.
All five methods are visible and checked by default. Use the checkboxes to
choose a subset, or **Select all methods** to restore the full comparison.
After the run finishes, both result selectors contain every computed method;
choose any pair without another rebuild. Computing all five does not change
the single-worker or 180-second limits. Clear selection disables Run merges.

The result reuses the offline explorer's complete hierarchy rendering, exact
visible-tip RF comparison, representative summaries, independent distance scales,
and optional client-side Newick exports. Changing input controls hides the old
result until Run merges succeeds. Navigation/collapse controls *within* a completed
result only reveal that run; they do not refit it. One method is displayed against
itself (RF zero). No biological ancestry or reference accuracy is claimed.

**Refresh Azure data** gets a new storage bearer token through `az`, downloads
only `manifest.json`, `embeddings.npz`, and `selected-records.tsv` directly into
RAM, verifies artifact SHA-256/byte counts and every ID/taxonomy row in source
order, and checks declared shape/counts. Each blob's actual ETag, SHA-256,
last-modified time, and the last-loaded UTC time appear in the source ledger.
An `If-Match` manifest recheck rejects changes during loading. A new generation
invalidates stale requests and all old results, even if refresh fails or is
cancelled; it never silently continues with an old snapshot. Provenance about
the original parent embedding bundle is manifest-declared, not a claim to have
reloaded that larger bundle.

There are **no local dataset or server-result files**, no result cache, no uploads,
no SAS, and no public-access changes. Explicit download buttons are optional
browser actions. Every Run is labeled newly computed. Only the latest result
and eight job status records are retained in memory. Stopping the service loses
them. A single spawned worker handles either refresh or computation; other jobs
receive HTTP 409. Cancel actually terminates numerical work, and a 180-second
deadline terminates stalled workers. Native numerical thread pools are limited
to one. Bounds: 8 KiB request bodies, 16 HTTP handlers, 64 MiB per source blob,
128 MiB uncompressed NPZ, 10,000 records, 512 dimensions, and at most 512 child
connectors. Oversized or mathematically invalid requests fail without subsampling.

The server binds **only `127.0.0.1`**. Same-origin checks, a per-process request
token, Host validation, no CORS, and `no-store` responses protect the local API
from cross-origin browser use and DNS rebinding. This is **not a deployed website
or multi-user authentication system**: local machine users can access it.
Do not reverse-proxy or tunnel it publicly. The compute/data adapter boundary
can support an Azure-hosted service later, but that requires actual user
authentication/authorization, managed identity, HTTPS, per-user isolation and
bounded cloud workers before changing this binding policy.

API: `GET /health`, `GET /api/source`, `POST /api/refresh` with `{}`,
`POST /api/jobs` with `{generation, path, methods, backend, maxChildren}`,
`GET /api/jobs/ID`, `POST /api/jobs/ID/cancel` with `{}`,
and `GET /api/jobs/ID/result` (JSON) or `/view` (rendered explorer).
Mutation requests require `Content-Type: application/json`, the exact same
`Origin`, and `X-Live-Token` from `/api/source`; this token is not an Azure token.
Status is `running`, `succeeded`, `failed`, or `cancelled`. Results superseded by
a new run return HTTP 410.

Validation:

```bash
uv run python -m pytest tests/test_live_tree.py tests/test_explorer.py \
  tests/test_hierarchy_representations.py --basetemp .pytest-live
node --test tests/explorer.test.cjs
# In-memory synthetic fixture, no Azure access:
uv run python tests/live_fixture.py --port 8766
node tests/live.browser.cjs http://127.0.0.1:8766/
node tests/explorer.browser.cjs http://127.0.0.1:8766/synthetic
# Against the real running private-Azure service (reads/refreshes only):
node tests/live.browser.cjs http://127.0.0.1:8765/ --real
```

Browser tests use an existing Playwright installation (`PLAYWRIGHT_MODULE`) and
optionally an existing Chromium/Edge executable (`PLAYWRIGHT_EXECUTABLE`).
Their browser scratch directories are repository-local and removed afterward;
real source/result payloads are never saved to files.

## Offline interactive merging lab

`tree explore` precomputes all five full-hierarchy trees using the `skbio`
backend and embeds every record and connector in one self-contained HTML file.
It does **not** include embedding vectors, credentials, external scripts, or
fonts. Controls navigate precomputed results; they do not perform live refitting.

For a private Azure subset with `embeddings.npz`, `selected-records.tsv`, and
the subset-creation `manifest.json`:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 uv run evospaice tree explore \
  --azure-prefix https://ACCOUNT.blob.core.windows.net/CONTAINER/PATH/TO/SUBSET/ \
  --subscription SUBSCRIPTION_ID --expect-records 5000 --publish
```

The command obtains a storage bearer token through the authenticated `az` CLI
(no ML extension), downloads directly to memory, verifies the manifest's NPZ/TSV
checksums and every metadata row, and rejects unexpected record exclusions.
The HTML is uploaded directly from memory to the **same prefix**, under a unique
`merging-explorer-<UTC>-<random>.html` name with `If-None-Match: *`. An authenticated
GET must reproduce its SHA-256 before success is reported. Source blobs are never
modified, no SAS is created, and container access policy is unchanged. Neither
dataset nor generated results are written locally. Omit `--publish` to stream
HTML to stdout instead. Progress goes to stderr. `--embeddings existing.npz`
also supports an already-local bundle and streams HTML to stdout.

The paired branching specimens expose actual connectors, searchable full-path
taxonomy, breadcrumbs and upward navigation, separate method selectors, incoming
tip lengths, per-method formulas and diagnostics, and selected/full-tree Newick
exports. Selected-taxon representative summaries include vector norm, cosine
deviation from the raw arithmetic mean, actual medoid record ID, or Gaussian
sample covariance trace. Point fits are deterministically replayed on completed
subtrees (GSC excludes incoming edges); Gaussian summaries use exact sample
moments. Only scalar summaries are embedded, not vectors or covariance matrices.
Reported runtime includes this inspection work. Topology-only layout is the default.
Branch-length mode uses independent
horizontal scales because cosine and W2 units differ. The selected root's incoming
edge is omitted from its view and exported subtree. Dotted label-alignment guides
are not edges.

Taxonomic tips summarize all their descendant records. Deeper collapse ranks reveal
the existing grafted subtree, not a new fit. More than 600 visible tips produces an
explicit refusal to draw (choose a smaller taxon or shallower rank), **not** a
partial or scientifically subsampled tree. Matching-tip links are hidden above
120 tips. Both limits affect display only; exports retain every record. The compact
encoding uses parent links and taxon-root indices rather than quadratic per-node
descendant lists.

Displayed split differences are exact **unrooted RF on the current collapsed tip
set**, deduplicating complementary root splits and excluding trivial splits.
Resolved zero-length edges remain in that topology. No reference accuracy is
claimed. Negative NJ edges are clamped, midpoint roots are conventions, and grafted
paths are not calibrated evolutionary distances. The embedded provenance ledger
includes source selection, checksums, versions, runtime, and excluded-record counts.

Validation: `uv run python -m pytest tests/test_explorer.py` and
`node --test tests/explorer.test.cjs`. Browser interactions are additionally
exercised by `tests/explorer.browser.cjs` (a Playwright page function); serve a
synthetic generated page from `tests/test_explorer.py::synthetic_dataset`, then
run `node tests/explorer.browser.cjs http://localhost:PORT/synthetic`. It can also
be imported as a page function. With an existing external Playwright installation,
set `PLAYWRIGHT_MODULE` to its module directory; `PLAYWRIGHT_EXECUTABLE` optionally
selects an existing Chromium/Edge executable. Browser artifacts stay under the
repository and are removed when the test finishes.

## Choose a full-hierarchy representation

```bash
uv run evospaice tree build \
  --embeddings /path/to/embeddings.npz \
  --all-families --method weighted \
  --output-dir results/full-weighted
```

`uv run python -m evospaice.tree.centroid` accepts the same options, including
`--method`. The module name is retained for compatibility. `centroid` remains
the default, with the original count-weighted arithmetic, root names,
`centroid.nwk` filename, and Biopython NJ backend. Other methods write
`medoid.nwk`, `weighted.nwk`, `wasserstein.nwk`, or `frechet.nwk`.

At **every** taxonomic node, the selected representation means:

| `--method` | Descendant representation and propagation |
| --- | --- |
| `centroid` | Arithmetic mean of all raw record vectors. Child means are weighted by descendant record counts, never equally by child count. |
| `medoid` | An actual descendant record minimizing total cosine distance to **all** descendant records. Candidates are not restricted to child medoids. For unit vectors `u`, the exact cosine total for candidate `i` is `n - u[i] @ sum(u)`, so this specialized exact search takes O(n d), not a quadratic distance matrix. The first input record wins numerical ties (score tolerance `16 * machine_epsilon * n`). |
| `weighted` | Recompute GSC weights over the **complete grafted descendant subtree**, including its internal connectors. Each leaf receives the sum of `edge length / number of descendants below that edge` on its path. Normalize weights and average the raw records. The incoming parent edge is excluded. Zero total length falls back explicitly to uniform record weights. |
| `wasserstein` | Refit the raw descendant mean and unbiased sample covariance. This includes between-child mean variation, unlike averaging child covariances. Singletons are point masses with zero covariance. No regularization or statistical rank truncation is used. |
| `frechet` | Fit squared angular distance on the unit sphere over **all normalized descendant records**, not child means. Deterministic Riemannian descent with line search starts at the normalized raw average of the unit vectors. It finds a stationary solution, not a guaranteed global minimum on arbitrary spherical data; antipodal ambiguity and nonconvergence are errors. |

All point methods use cosine dissimilarity for both record-level and parent
NJ connectors. Frechet uses angular distances only for fitting its
representative; its branch lengths are **not** angular distances. Gaussian
connectors use Gaussian W2, with Euclidean distance between record point
masses, so W2 can also change the species-level topology. These choices match
the survey's representation formulas, with unregularized covariance and
explicit spherical numerical limits rather than assumed uniqueness.

### Resources and limitations

`--max-children` (default 512) is checked before allocating local pairwise
distances and rejects oversized taxa without dropping records. Taxa are grouped
by their full ancestor path, so repeated genus/species labels under different
parents remain separate. There is no global all-record pairwise matrix in a
full build. A single species containing all records is still a local NJ
problem and is subject to this fan-out limit.

Local NJ still has quadratic distance storage and potentially cubic runtime.
The representation work is additional: medoid and raw-vector scans use O(n d)
per taxon; GSC also traverses its full descendant tree. Frechet performs up
to 256 iterations with up to 40 line-search trials per iteration. Repeated
descendant scans require record-vector workspace; these are not streaming
or constant-memory implementations.

Gaussian factors are compressed by exact QR when the number of records
exceeds the dimension, yielding at most `d` factor columns. This preserves
the entire sample covariance, including between-group variance, and prevents
W2 factor products from growing with descendant count. Fitting can still
cost O(n d²), sibling factors occupy up to O(children × d²), and each W2 pair
can require an O(d³) SVD. High-dimensional/high-fan-out Gaussian builds can
therefore be expensive even with compiled NJ.

`--max-representative-records N` is an optional explicit descendant-count
guard, including the final root (thus also limiting the selected cohort).
There is no default cap. It is not a memory/time guarantee and does not
limit dimension. Reduce the cohort or fan-out rather than assuming all
methods have centroid-scale performance. NJ backend choices apply to all
methods; neither backend changes the representation mathematics. Repeated
runs with the same inputs/backend are deterministic; record order breaks
medoid ties, and numerical/backend differences can change tied resolutions.

Reports identify method, propagation, geometry, units, and all four ranks.
The full-build `embedding_distance` and `evaluated-pairs.tsv` use the native
leaf target: cosine for point methods, raw Euclidean for W2. W2's extra
cosine comparison reports correlations only, explicitly marking raw
magnitudes incomparable. Undefined stress (zero target norm), constant-data
correlations, and singleton/no-pair metrics are `null`, not fabricated zeros.
None of these errors or correlations calibrates evolutionary branch lengths.

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
  --output-dir results/butterfly-centroid
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

`uv run python -m pytest tests/test_centroid.py tests/test_centroid_backends.py
tests/test_compare_representations.py tests/test_hierarchy_representations.py
tests/test_cli_tree.py` covers filtering, both backends, higher-rank
representation mathematics, uneven child sizes, taxonomy monophyly,
zero/singleton cases, resource limits, reproducibility, compatibility,
and NPZ-to-Newick CLI outputs for all methods.

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

The genus comparison delegates to the same recursive builder, starting at
the selected genus; it remains an intentionally genus-only comparison,
whereas `tree build --method ...` builds the entire selected hierarchy.

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
parent connectors, so local topology can differ too. Its unbiased covariance
is represented by an exact factor capped at the embedding dimension;
singleton species have zero covariance. The Bures covariance term uses the
nuclear norm of the product of the two factors, avoiding dense covariance square roots.
No artificial covariance regularization is added.

W2 lengths and cosine lengths have different units. The page defaults to
topology-only layout and uses independent scales in branch-length mode.
Comparisons report unrooted RF, cosine-distance rank correlation, and reference
path correlation on all leaf pairs. Raw W2/reference magnitude errors against
cosine are `null` and labeled incomparable; native W2 errors use Euclidean
leaf targets. The JSON's optional scalar-aligned stress
is fitted on those same pairs: it is descriptive, not held-out evaluation or
biological calibration. The shared NJ helper retains the original centroid
baseline behavior, including negative-edge clamping and no attachment correction.
