# Reference-tree versus embedding EDA

Create an **offline, interactive scatterplot** comparing original reference-tree
path distances with cosine distances between original embedding vectors.
This standalone tool does not construct an NJ tree, fit branches or compute
centroids.

## Run

Run from the repository root with the existing environment:

```powershell
.\.venv\Scripts\python.exe -m evospaice.embeddings.eda --help
```

The package uses NumPy, SciPy and DendroPy. It does not load a neural model, require a GPU, use a server/CDN, or upload data.

### Sample 1,000 matched records from any compatible dataset

```powershell
.\.venv\Scripts\python.exe -m evospaice.embeddings.eda `
  --input "data\dnabert\dnabert-s_BOLD_Public.30-Jun-2026-Lepidoptera-BIN-representatives.npz" `
  --reference "data\pruned.tre.txt" `
  --sample-size 1000 `
  --seed 42 `
  --embedding-model DNABERT-S `
  --color-by family `
  --output-dir "outputs\eda_dnabert_1000"
```

Open **`outputs\eda_dnabert_1000\scatter.html`** directly in your browser.
The sample size is a **number of matched BIN records, not pairs or unique
species labels**: 1,000 records produce 499,500 unordered pairs.

Change `--input` to use Omni-DNA or another compatible NPZ. Change `--reference`
to compare against a different Newick or Nexus tree. No source paths are hardcoded
as CLI input defaults.

### All matching records in Papilionidae, including Papilio

```powershell
.\.venv\Scripts\python.exe -m evospaice.embeddings.eda `
  --input "data\dnabert\dnabert-s_BOLD_Public.30-Jun-2026-Lepidoptera-BIN-representatives.npz" `
  --reference "data\pruned.tre.txt" `
  --family Papilionidae `
  --all-matches `
  --embedding-model DNABERT-S `
  --color-by genus `
  --output-dir "outputs\eda_dnabert_papilionidae"
```

In the HTML, choose **Within genus: Papilio** to examine only pairs with both
records in Papilio, or **All genera** to include between-genus pairs.
Genera with only one match remain in the dataset but have no within-genus pairs.
Genera without reference matches are reported in `genus_coverage.csv`.

### Analyze only Papilio

```powershell
.\.venv\Scripts\python.exe -m evospaice.embeddings.eda `
  --input "data\omni20m\omni-dna-20m_BOLD_Public.30-Jun-2026-Lepidoptera-BIN-representatives.npz" `
  --reference "data\pruned.tre.txt" `
  --family Papilionidae `
  --genus Papilio `
  --all-matches `
  --embedding-model omni-dna-20m `
  --output-dir "outputs\eda_omni_papilio"
```

Unlike the browser filter, `--genus` restricts which records and pairs are
exported. If `--family` is omitted, the genus's single known parent family is
inferred from eligible input metadata; ambiguous or missing ancestry requires
an explicit `--family`.

## Options

| Option | Default | Meaning |
|---|---|---|
| `--input PATH` | Required | Original embedding NPZ |
| `--reference PATH` | Required | One Newick or Nexus reference tree |
| `--output-dir PATH` | `outputs\eda` | New or empty experiment directory |
| `--sample-size N` | `1000` | Sample N matched records without replacement; minimum 2 |
| `--all-matches` | Off | Include all scoped matches; mutually exclusive with `--sample-size` |
| `--seed N` | `42` | Nonnegative sampling seed; unused for all-matches runs |
| `--family NAME` | No restriction | Exact, case-sensitive family label |
| `--genus NAME` | No restriction | Exact genus label; optionally infer its parent family |
| `--embedding-model NAME` | Unspecified | Label for headings/provenance, not a model loader |
| `--color-by MODE` | `relationship` | Initial color mode: `relationship`, `family`, `genus`, `species` |
| `--max-pairs N` | `2000000` | Explicit pair-count limit before distance-matrix allocation |

Every run includes all color modes and filters in **one HTML**; no second
color-export command is necessary. Model labels are user-supplied except that
the known Omni-DNA-20M input can be named from its verified SHA-256. Other
unlabeled inputs receive a generic heading rather than an invented model name.

Existing output directories must be empty. Existing experiments and inputs are
never overwritten. Use a different output directory for another configuration.

### Scale and memory

N selected records produce N(N-1)/2 pairs. `--all-matches` also works without a
family/genus filter, but the pair budget still applies. If the requested count
exceeds `--max-pairs`, the run fails explicitly: it does not silently reduce
the sample. Reduce the sample or narrow the taxonomy scope.

The complete NPZ is loaded and retained rows validated. A float64 distance
matrix is computed only for selected records; no all-reference-tip distance
matrix is constructed. Pair exports and HTML nevertheless grow quadratically.
The default budget permits up to 2,000 selected records; 2,001 would exceed it.
Raise `--max-pairs` only after considering RAM, file size and browser performance.

## Input contract and scientific policies

The NPZ must be readable with `allow_pickle=False` and contain:

| Array | Shape | Content |
|---|---|---|
| `embeddings` | `(records, dimensions)` | Real numeric embedding vectors, any positive dimension |
| `ids` | `(records,)` | Unique source record IDs matching reference tip labels |
| `bin_uri` | `(records,)` | Unique BIN identifiers |
| `species`, `genus`, `family`, `order` | `(records,)` each | Taxonomy metadata |

Additional NPZ arrays must also be one-dimensional and row-aligned.
Object/pickle-based files, duplicate record/BIN IDs, and retained zero/nonfinite
vectors are rejected.

The exact, case-sensitive **`species == "None"` filter is applied first**, before
quality checks or taxonomy analysis. Additional missing species are excluded
separately. Missing genus/family does not automatically remove otherwise usable
records from an unscoped distance analysis. Labels are not renamed or case-folded.

Reference tips must have unique, nonempty record IDs. Matching is exact; species
names are not used as substitute IDs. Underscores in tip labels are preserved.
Newick and Nexus are detected automatically; the file must contain exactly one
tree. Nonfinite or negative nonroot reference lengths are errors.

Each selected record remains a separate BIN representative, including repeated
species labels. Sampling is uniform without replacement from lexicographically
sorted scoped matches. All unordered pairs within the selected records are
evaluated using:

- Reference patristic distance: sum of original branch lengths along the path.
- Embedding cosine distance: `1 - cosine similarity` after robust float64 L2
  normalization of original vectors.

Missing reference edges exclude only paths crossing those edges; they are not
silently replaced with resolved zero lengths. Undefined correlations are reported
explicitly for fewer than two valid pairs or constant distance arrays.
Input hashes are checked before and after successful runs.

## Interactive controls

The page supports zoom/pan, point hover/pinning, focal-record filtering,
relationship checkbox combinations, a regression line, and CSV downloads.
Family/genus-scoped runs also provide a within-genus selector.
Correlation cards apply to the active filters, **not the zoom viewport**.
The relationship summary table always describes the entire exported analysis.

Each point represents **two records**. In taxonomy color modes, matching known
taxa share a color; different taxa are gray and incomplete taxonomy is light
gray. Genus identity includes family, and species identity includes genus and
family. Colors may look similar for many taxa; inspect labels to identify them.
Changing colors does not change distances, filters or correlations.

## Outputs

| File | Content |
|---|---|
| `scatter.html` | Self-contained plot, model label, all filters/color modes and provenance |
| `sampled_records.csv` | Selected records with original source-row indices and taxonomy |
| `pairwise_distances.npz` | Complete pair arrays, relationship codes and validity mask |
| `summary.json` | Input hashes, dimensions, scope/selection counts, correlations and fit |
| `genus_coverage.csv` | Eligible/matched/analyzed genus counts for a scoped run |

`sampled_records.csv` retains its name even with `--all-matches`; the summary and
HTML explicitly state that no random subsampling occurred.
NPZ pair indices `sample_i`/`sample_j` index the CSV record order.
`reference_tree_distance` is NaN for unknown paths, accompanied by
`valid_reference_path=False`; those pairs are excluded from the HTML.
`embedding_cosine_distance` contains original-vector distances.
Relationship codes are 0: same species label, 1: same genus/different species,
2: same family/different genera, 3: different families, 4: unknown relationship.

Browser pair downloads include up to 5,000 visible pairs; the NPZ contains all
pairs. On a computation/export failure, created success files are removed and
`failure.json` records the error. Argument validation may fail before a directory
is created.

## Interpretation

Pearson measures linear association; Spearman measures rank association.
Different units do not require normalizing the axes for these correlations.
No identity line, cross-unit raw RMSE, or naive pair-level p-values/confidence
intervals are reported. Pairs share records and are not independent. Uneven
taxon representation and between-family pairs can dominate pooled results.
Agreement with a reference is not itself proof of evolutionary accuracy.

## Files

The tool consists of three files:

- `__main__.py`: command-line options, loading, selection, distances, colors and exports.
- `scatter.html`: the self-contained interactive HTML template.
- `README.md`: usage and scientific policies.

The command remains `python -m evospaice.embeddings.eda`. No additional local
Python modules are required.
