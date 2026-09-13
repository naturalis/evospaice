# Evospaice: solution design and work plan

## 1. What we are building

Evospaice will build one genetic reference tree for insects using the
Leray-313 region of the COI barcode. It starts with DNA records and taxonomic
labels from BOLD. It ends with a tree whose branch lengths show estimated
genetic difference.

The main idea is simple:

> Use the existing taxonomy as the basic tree. Use DNA embeddings to improve
> crowded parts of that tree and estimate branch lengths.

We will compare two ways of measuring genetic difference:

- **Primary method:** cosine distance between DNABERT-S embeddings.
- **Control method:** a sourmash/FracMinHash k-mer distance.

Running both methods through the same pipeline shows whether the embedding is
a useful distance measure, rather than only a useful species identifier.

### What we will deliver

- A repeatable pipeline that works from raw BOLD data to a scaled tree.
- One end-to-end result for a manageable, real subset of insect COI data.
- A report showing where embedding distances can and cannot be trusted.
- A visual example of the tree and a recommendation for future work.

### What we will not build this week

- A tree inferred from scratch from every DNA sequence.
- A newly trained DNA model.
- A custom interactive tree viewer.
- A production run over the complete BOLD database.
- A full sample-placement system.

### Rules that keep the solution practical

1. Start with the taxonomy tree; do not build a global tree from scratch.
2. Trim every sequence to the same Leray-313 window before comparing it.
3. Remove duplicates only within the same taxon or BIN. Never merge identical
  sequences from different taxa.
4. Store vectors, not a matrix containing every possible pairwise distance.
5. Calculate distances only for the small group of children currently being
  processed.
6. Resolve tree shape and calculate branch lengths in the same bottom-up pass.
7. Split very large groups into smaller groups before running NJ.
8. Let validation decide how deep in the tree the embedding can be trusted.

## 2. How the solution works

### 2.1 Inputs and outputs

```text
INPUTS
  - BOLD DNA sequences and taxonomy
  - Fine-tuned DNABERT-S model
  - Trusted reference tree for validation
      |
      v
  EVOSPAICE PIPELINE
      |
      +--> Scaled reference tree
      +--> Validation and run reports
      +--> Tree visualisation
      +--> Optional diversity and data-quality examples
```

### 2.2 Processing steps

```text
1. READ AND CLEAN
  Read BOLD data -> keep insect COI records -> trim to Leray-313
      |
      v
2. PREPARE INPUTS
  Select one representative per BIN -> build the taxonomy backbone
      |
      +--> records.tsv
      +--> backbone.nwk
      |
      v
3. CREATE TWO COMPARABLE DISTANCE SOURCES
  DNABERT-S embeddings                 FracMinHash signatures
      |                                      |
      +------------------+-------------------+
                  v
4. BUILD THE TREE
  Walk from tips to root -> compare direct children -> resolve safe groups
  -> calculate branch lengths -> save one representative for the parent
      |
      +--> scaled-tree.nwk
      +--> node-diagnostics.tsv
      |
      v
5. VALIDATE
  Compare with a trusted tree -> decide which ranks/depths are reliable
      |
      +--> validation-report.json
      +--> trust-policy.json
      |
      v
6. APPLY THE POLICY AND PRESENT THE RESULT
  Rebuild with the approved limits -> render -> report -> decide next steps
```

### 2.3 Where each part runs

This is a restartable batch pipeline, not a live web service.

| Location | Work done there | How it scales |
| --- | --- | --- |
| Developer machine or CI | Tests, small fixtures, file checks, and small full-pipeline runs | One process is enough |
| CPU workers | Read BOLD data, build taxonomy, calculate k-mers, and build the tree | Split source files or independent taxonomic subtrees |
| GPU workers | Run DNABERT-S on batches of sequences | Run independent batches and merge them by record ID |
| File or object storage | Keep inputs and the outputs of each run | Use a separate directory for every run |

The prototype does not need network APIs between components. Teams exchange
versioned files. This keeps runs repeatable and lets teams work against small
test files while full data processing is still running.

## 3. Terms used in this plan

| Term | Plain-language meaning |
| --- | --- |
| **Artifact** | A file produced or used by one pipeline step |
| **Backbone** | The starting tree taken from BOLD taxonomy |
| **BIN** | BOLD's identifier for a cluster of similar barcode sequences |
| **Embedding** | A numeric vector that represents one DNA sequence |
| **k-mer** | A short DNA substring; k-mer overlap provides the control distance |
| **Polytomy** | One tree node with many direct children: an unresolved "bush" |
| **NJ** | Neighbor-Joining, an algorithm that turns a distance table into a local tree |
| **Centroid** | The average vector used to represent a completed group |
| **Medoid** | A real child vector chosen to represent a group when its average is unreliable |
| **Post-order** | Process all children before processing their parent |
| **Trust policy** | Rules that say where distances may be used to resolve or scale the tree |
| **Newick** | The text file format used to store a tree |

## 4. Software parts

| Part | Code location | What it does |
| --- | --- | --- |
| BOLD reader | `evospaice.ingest` | Reads plain, compressed, or archived BOLD files and handles missing values |
| Sequence trimmer | `evospaice.ingest` | Finds the Leray window in either direction, trims it, and rejects poor records |
| Representative selector | `evospaice.ingest` | Chooses records within each BIN in a repeatable way and keeps their source details |
| Backbone builder | `evospaice.ingest` | Turns BOLD taxonomy into a Newick tree and sidecar table |
| Embedding runner | `evospaice.ingest` | Runs DNABERT-S in batches and saves one vector per retained record |
| k-mer runner | `evospaice.ingest` | Creates the FracMinHash control from the same records |
| Input checker | `evospaice.tree` | Confirms that files, IDs, vector sizes, and tree tips match before work starts |
| Distance provider | `evospaice.tree` | Calculates only the requested embedding or k-mer distances |
| Group representative | `evospaice.tree` | Chooses one fixed centroid or medoid for a completed node |
| Local tree resolver | `evospaice.tree` | Uses NJ on approved groups and splits groups that are too large |
| Branch-length calculator | `evospaice.tree` | Calculates edge lengths and uses the stronger NNLS fallback when needed |
| Tree walker | `evospaice.tree` | Runs the bottom-up process and saves progress and diagnostics |
| Distance validator | `evospaice.validate` | Tests depth, additivity, and short terminal branches against reference data |
| Trust-policy builder | `evospaice.validate` | Turns validation results into rules used by the tree builder |
| Visual exporter | `evospaice.viz` | Creates smaller tree extracts, static figures, and files for iTOL |
| Diversity calculator | `evospaice.diversity` | Demonstrates Faith's PD and UniFrac on small placed samples |
| Command-line runner | `evospaice.cli` | Gives all stages consistent commands, settings, logs, and error codes |

## 5. Files passed between workstreams

Each run writes to `runs/<run-id>/`. Large outputs stay out of Git. Small test
files belong in `data/` or `tests/fixtures/`.

### 5.1 Required files

| File | What it contains |
| --- | --- |
| `records.tsv` | One row for each retained record or BIN, including its stable ID, taxonomy, trimmed sequence, primer result, orientation, quality values, and original source row |
| `embeddings.npy` | One finite `float32` vector per row of `records.tsv`, in the same order |
| `baseline.sig` or signature shards | One sourmash signature per retained record, built from the same trimmed sequences |
| `backbone.nwk` | The starting taxonomy tree; every tip has a unique BIN ID and existing BOLD notes are preserved |
| `manifest.json` | Everything needed to reproduce the run: versions, settings, model ID, source and output checksums, row counts, vector size, and random seeds |
| `trust-policy.json` | The ranks or depths where each metric is approved, the thresholds used, and the validation report that supports the decision |
| `scaled-tree.nwk` | The final tree with finite, non-negative branch lengths; unsupported groups stay unresolved |
| `node-diagnostics.tsv` | What happened at each node: size, method, metric, confidence, errors, runtime, clamped lengths, and fallback |
| `validation-report.json` | The validation scores, uncertainty, pass/fail results, reference version, and recommended trust policy |

### 5.2 Rules for exchanging files

1. A `record_id` never changes and is unique within a run.
2. The row order in `records.tsv` defines the row order in `embeddings.npy`.
   Readers must still check IDs and file checksums before joining files.
3. Every tree tip has exactly one vector, or appears in a clear exclusion list.
   Never silently drop tips while joining files.
4. Distances must be finite, non-negative, symmetric, and zero when a record is
   compared with itself. Never save a global all-pairs distance matrix.
5. Create a node representative once, give every direct child equal weight,
   and do not change it after processing its parent begins.
6. Branch lengths must be finite and non-negative. Change a negative result to
   zero and record that change in the diagnostics.
7. Record the random seed for every method that uses randomness.
8. Every output points back to the input manifest and settings that created it.

### 5.3 Shared code interfaces

The exact implementation can change, but the main interfaces should stay small:

```python
class DistanceProvider(Protocol):
    name: str

    def pairwise(self, record_ids: Sequence[str]) -> np.ndarray: ...


class RepresentativeReducer(Protocol):
    def reduce(self, child_ids: Sequence[str], vectors: np.ndarray) -> np.ndarray: ...


class ResolutionPolicy(Protocol):
    def should_resolve(self, rank: str, child_count: int, confidence: float) -> bool: ...
```

The tree walk, diagnostics, and validation must work in exactly the same way
with either the embedding distance or the k-mer distance.

## 6. How one tree node is processed

For a detailed module design, pseudocode, and test plan starting from existing
vectors and ID-linked metadata, see
[Building the tree from precomputed embeddings](tree-implementation.md).

The system starts at the tips and moves toward the root. At each node it:

1. Gets the fixed representative vector for each direct child.
2. Leaves the shape alone when the node has fewer than three children.
3. Checks the trust policy to see whether this rank or depth may be resolved.
4. If approved, calculates distances between these children and runs NJ.
5. If the node has too many children, splits them into about $\sqrt{k}$ smaller
   groups, resolves each group, and then joins the group representatives.
6. Calculates branch lengths. If the normal method fits poorly, it retries
   with NNLS. Any negative length becomes zero and is reported.
7. Calculates an average representative in which every child has equal weight.
   If that average is unreliable, it uses the nearest real child instead.
8. Saves the completed subtree, its representative, and a diagnostics row.

For a node with $k$ children, its temporary distance table uses $O(k^2)$
memory. The whole tree never has a global $O(n^2)$ distance table.

## 7. Errors, progress, and recovery

- Check IDs, checksums, vectors, and Newick before starting expensive work.
- Stop with a clear error for duplicate IDs, missing vectors, mismatched vector
  sizes, damaged trees, or non-finite values.
- Keep uncertain taxonomy records, but mark and isolate them. Do not silently
  guess their biological classification.
- Report the current stage, shard, taxon, processed and rejected record counts,
  speed, elapsed time, and memory use where available.
- Make each step safe to rerun. Reuse an output only when its checksum and
  settings match the current run.
- Save progress at subtree boundaries so a failed tree run can continue from
  its latest valid checkpoint.
- Record every fallback and quality warning. A run may complete technically
  while still producing scientifically weak results.

## 8. Workstreams and task backlog

Each workstream can have its own owner. The task table uses:

- **P0:** needed for the hackathon result.
- **P1:** needed for a reliable decision or a larger run.
- **P2:** optional demonstration work.
- **Depends on:** tasks that must finish first.
- **Done when:** the evidence required to close the task.

### 8.1 Inputs, outputs, and handoffs

Yes, some workstream outputs are required inputs for other workstreams. The
workstreams are not one long sequence, however. Several can start together,
and WS3 and WS4 have one planned feedback loop.

| Workstream | Inputs it needs | Outputs it produces | Who needs those outputs |
| --- | --- | --- | --- |
| **WS0 - Foundation** | Hackathon brief, repository, agreed scope, and tool constraints | File schemas, ID and naming rules, test dataset, common configuration pattern, CLI structure, CI checks, and benchmark rules | Every other workstream |
| **WS1 - Ingest and backbone** | BOLD BCDM release, Leray primer settings, and WS0 file/ID rules | `records.tsv`, exclusion list, ingest report, source manifest, `backbone.nwk`, sidecar metadata, and small test subsets | WS2, WS3, WS4, WS5, and WS6 |
| **WS2 - Embeddings and baseline** | WS1 `records.tsv` and manifest, DNABERT-S model, and WS0 file rules | `embeddings.npy`, FracMinHash signatures, embedding manifest, distance-provider code, failed-record report, and performance results | WS3, WS4, and WS5 |
| **WS3 - Tree building** | WS1 backbone and records, WS2 vectors/signatures and distance providers, and a provisional or validated trust policy | Candidate and final `scaled-tree.nwk`, `node-diagnostics.tsv`, subtree checkpoints, and tree performance results | Candidate tree goes to WS4; final tree goes to WS5, WS6, WS7, and WS8 |
| **WS4 - Scientific validation** | Trusted COI reference tree, WS1 records, WS2 distance providers, and the WS3 candidate trees and diagnostics | `validation-report.json`, `trust-policy.json`, calibration decision, deep-branch fallback, and scientific recommendation | WS3 uses the policy for the final tree; WS5, WS6, and WS8 use the evidence |
| **WS5 - Integration and scale** | Components and outputs from WS0 through WS4 | End-to-end run command, run configuration, combined logs, reproducible run package, scale measurements, full-scale design, and release checklist | WS8, and the team planning a full-scale run |
| **WS6 - Visualisation** | WS1 backbone/test subsets, then WS3 tree/diagnostics and WS4 validation results | Extracted clade trees, iTOL annotation files, comparison charts, and final figures | WS8 and project reviewers |
| **WS7 - Diversity and curation** | WS3 final tree, sample-to-tip data, WS1 quality report, and relevant WS4 confidence rules | Faith's PD and UniFrac results, metric comparisons, and a traceable list of suspect records | WS8 and future application work |
| **WS8 - Demo and decision** | Reproducible WS5 run, WS3 final tree, WS4 conclusions, WS6 figures, and optional WS7 results | Setup guide, result package, demo narrative, final recommendation, and follow-on backlog | Project sponsors and the next engineering phase |

#### Required handoffs

```text
WS0 shared rules and test data
  |
  +--> WS1 clean records and taxonomy backbone
  |      |
  |      +--> WS2 embeddings and k-mer baseline
  |      |      |
  |      |      +--> WS3 candidate tree
  |      |                 |
  |      +-----------------+--> WS4 validation and trust policy
  |                                |
  |                                +--> WS3 final gated tree
  |                                           |
  +-------------------------------------------+--> WS5 reproducible run
                               +--> WS6 figures
                               +--> WS7 optional applications
                                      |
                                      v
                                  WS8 final decision
```

The minimum blocking handoffs are:

1. **WS0 to all teams:** shared file formats, IDs, and the small test dataset.
2. **WS1 to WS2:** cleaned `records.tsv`; embedding must not start from raw or
  differently trimmed sequences.
3. **WS1 and WS2 to WS3:** the backbone, matching record IDs, and at least one
  working distance provider.
4. **WS2 and WS3 to WS4:** comparable distances and candidate trees for the
  same records.
5. **WS4 back to WS3:** `trust-policy.json`, which controls the final tree run.
6. **WS3 and WS4 to WS5/WS6/WS8:** the final tree plus evidence describing
  which parts are trustworthy.

Work that does **not** need to wait:

- WS1 can improve BOLD parsing while WS0 finalises schemas, using temporary
  fixtures until the contract is frozen.
- WS2 can prepare model loading and batch inference before the full cleaned
  dataset is available.
- WS3 can build against the small precomputed vectors from WS0/WS2.
- WS4 can select the reference tree and define tests before candidate results
  exist.
- WS5 can build configuration, logging, and CI from the start.
- WS6 can evaluate tools with the unscaled backbone before the final tree.
- WS7 is optional and should wait until the final tree contract is stable.

### 8.2 Detailed task lists

### WS0 - Architecture, contracts, and delivery foundation

This team defines the shared rules, test data, and development setup used by
all other teams.

| ID | Priority | What to do | Depends on | Done when |
| --- | --- | --- | --- | --- |
| ARC-01 | P0 | Agree on the scope, key terms, excluded work, and design rules | - | The team accepts the rules in sections 1 and 5 |
| ARC-02 | P0 | Define and version the formats of shared files | ARC-01 | Each format has a valid example, and invalid examples are rejected |
| ARC-03 | P0 | Set rules for IDs, row order, checksums, run folders, and file names | ARC-02 | Files created by different teams can be joined with the same result every time |
| ARC-04 | P0 | Create a small, licensed BOLD-like test dataset with a known result | ARC-02 | It covers reversed DNA, ambiguous bases, duplicate BINs, missing ranks, and a many-child node |
| ARC-05 | P0 | Connect each CLI command to its pipeline stage and shared settings | ARC-02 | `evospaice --help` shows working options and commands return useful exit codes |
| ARC-06 | P0 | Add automated formatting, unit, and small end-to-end checks | ARC-04 | Ruff and pytest pass from a clean checkout |
| ARC-07 | P1 | Track where every output came from and support restarting stages | ARC-03 | A rerun reuses output only when its inputs and settings match |
| ARC-08 | P1 | Define one performance test and record CPU, GPU, memory, time, and file size | ARC-04 | Every candidate run produces comparable measurements |
| ARC-09 | P1 | Check BOLD terms, model licence, CC0 output rules, and secret handling | ARC-01 | The release review finds no unresolved legal or credential issue |

### WS1 - Source data, primer-window ingest, and taxonomy backbone

This team turns the raw BOLD release into clean, comparable records and the
starting taxonomy tree.

| ID | Priority | What to do | Depends on | Done when |
| --- | --- | --- | --- | --- |
| ING-01 | P0 | Choose the exact BOLD release, source file, insect filter, COI-5P marker, and Leray primer settings | ARC-03 | The manifest records the source checksum and every selection setting |
| ING-02 | P0 | Read plain, gzip, and tar BCDM input without unpacking large files first | ARC-04 | The same test data produces identical records in all three formats |
| ING-03 | P0 | Clean each sequence, find its direction and primers, and trim it to Leray-313 | ING-01 | The test sequences produce the hand-checked windows and positions |
| ING-04 | P0 | Reject sequences that are too short or ambiguous and record each reason | ING-03 | Input, retained, and rejected counts add up exactly |
| ING-05 | P0 | Choose representatives only within each BIN or taxon, using repeatable tie-breaks | ING-03, ING-04 | Equal DNA in different taxa stays separate, and reruns select the same rows |
| ING-06 | P0 | Write `records.tsv`, the exclusion list, ingest report, and manifest details | ARC-02, ING-05 | File-format, count, and checksum checks pass |
| ING-07 | P0 | Build and check the taxonomy backbone with its BOLD notes | ING-01 | The Newick tree is valid, rooted, and contains each expected BIN once |
| ING-08 | P0 | Match retained records to backbone tips and explain every missing or extra ID | ING-06, ING-07 | There are no unexplained ID differences |
| ING-09 | P1 | Report primer quality, taxonomy coverage, moved/suspect tips, and sampling imbalance | ING-06, ING-07 | The report identifies risky groups and supports the chosen quality limits |
| ING-10 | P1 | Create genus-, family-, and order-sized datasets for downstream tests | ING-08 | Other teams have small, medium, and high-fan-out examples |
| ING-11 | P1 | Measure a full-release streaming pass and estimate required resources | ING-09, ARC-08 | The full-scale estimate is based on measured processing speed |

### WS2 - Embeddings and k-mer baseline

This team converts the same cleaned sequences into the primary embedding
vectors and the control k-mer signatures.

| ID | Priority | What to do | Depends on | Done when |
| --- | --- | --- | --- | --- |
| EMB-01 | P0 | Choose the exact model, tokenizer, version, pooling, normalisation, precision, and sequence limit | ING-01 | The locked model settings are recorded in the manifest |
| EMB-02 | P0 | Generate embeddings in repeatable batches from the cleaned sequences | ING-06, EMB-01 | Every test ID has one finite vector with the expected size and order |
| EMB-03 | P0 | Save vectors in batches and merge them into `embeddings.npy` in canonical row order | EMB-02, ARC-03 | Batched and single-process results match within the agreed tolerance |
| EMB-04 | P0 | Build FracMinHash signatures from exactly the same retained sequences | ING-06 | Every canonical ID has one valid signature |
| EMB-05 | P0 | Provide cosine and k-mer distance calculators behind one interface | EMB-03, EMB-04 | Tests show finite, symmetric distances, a zero diagonal, and on-demand access only |
| EMB-06 | P0 | Record batch status, failed records, and checksums so inference can resume | EMB-03, ARC-07 | An interrupted run resumes and cannot publish incomplete vectors as complete |
| EMB-07 | P1 | Measure GPU batch size, precision, speed, memory, and numerical stability | EMB-02, ARC-08 | The recommended settings and estimated subset runtime are documented |
| EMB-08 | P1 | Find duplicate, zero-length, constant, and unusual vectors | EMB-03 | Invalid vectors stop the run and suspicious vector IDs appear in a report |
| EMB-09 | P1 | Commit a small set of precomputed vectors for CPU-only development | EMB-03, ARC-04 | Tree and validation tests run without a model or GPU |

### WS3 - Resolve taxonomy and assign branch lengths

This team improves each approved many-child group, calculates branch lengths,
and assembles the final tree in one bottom-up pass.

| ID | Priority | What to do | Depends on | Done when |
| --- | --- | --- | --- | --- |
| TRE-01 | P0 | Load the backbone, records, vectors, metric, and trust policy, checking that they match | ARC-02, ING-08, EMB-05 | Bad joins stop before tree processing, and the test dataset loads correctly |
| TRE-02 | P0 | Walk the tree from children to parents without recursion or unbounded memory | TRE-01 | Children always finish first, and a deep test tree does not overflow the call stack |
| TRE-03 | P0 | Create one fixed average vector per node, giving each child equal weight | TRE-02 | Tests show that large subtrees do not get extra weight |
| TRE-04 | P0 | Detect an unreliable average and use the nearest real child vector instead | TRE-03 | Crossing the configured limit selects a medoid and records the reason |
| TRE-05 | P0 | Calculate distances only between the current node's direct children | TRE-02, EMB-05 | A test proves that no unrelated record distance is requested |
| TRE-06 | P0 | Use NJ to resolve approved many-child nodes without losing labels or notes | TRE-05 | A small known example produces the expected local branches |
| TRE-07 | P0 | Implement the paper's bottom-up branch-length calculation | TRE-05 | A synthetic tree recovers its known lengths within tolerance |
| TRE-08 | P0 | Change negative lengths to zero and report fit errors and every change | TRE-07 | All output lengths are finite and non-negative, and counts match the diagnostics |
| TRE-09 | P0 | Resolve local shape and calculate lengths during the same visit to each node | TRE-03, TRE-06, TRE-08 | One tree walk produces a valid scaled test tree |
| TRE-10 | P0 | Use rank, depth, and confidence rules to decide which nodes may be resolved | VAL-08, TRE-09 | Rejected deep nodes stay unresolved and are marked in diagnostics |
| TRE-11 | P1 | Retry poor branch-length fits with NNLS and record why it was used | TRE-08 | A difficult test case chooses NNLS and reports the trigger and fit |
| TRE-12 | P1 | Split nodes above the NJ child limit into about $\sqrt{k}$ smaller groups | TRE-06 | A stress test stays within memory limits and keeps every child exactly once |
| TRE-13 | P1 | Save completed subtrees and restart from them repeatably | TRE-09, ARC-07 | A stopped run resumes without rebuilding completed subtrees |
| TRE-14 | P1 | Check the final Newick, tips, branch lengths, and saved annotations | TRE-09 | Input and output tip sets match, and more than one parser accepts the file |
| TRE-15 | P1 | Measure time and memory for different node and subtree sizes with both metrics | TRE-12, ARC-08 | The report shows practical limits and estimated full-scale cost |

### WS4 - Scientific validation and trust policy

This team answers the central scientific question: where are embedding
distances reliable enough to shape and scale the tree?

| ID | Priority | What to do | Depends on | Done when |
| --- | --- | --- | --- | --- |
| VAL-01 | P0 | Choose a trusted insect COI tree and document its licence, marker match, and taxonomy mapping | ARC-09 | The reference can be reproduced and overlaps the retained BOLD data |
| VAL-02 | P0 | Map BOLD records and taxa to reference-tree tips with a complete audit trail | VAL-01, ING-06 | The report counts matches, ambiguous cases, and exclusions with no hidden many-to-one match |
| VAL-03 | P0 | Set the tests, comparison baselines, sample sizes, uncertainty method, and pass limits in advance | VAL-01 | The team reviews a versioned protocol that can be run as code |
| VAL-04 | P0 | Test whether distances preserve the expected order from species through order | VAL-02, EMB-05 | The report gives rank correlation and uncertainty for embeddings and k-mers |
| VAL-05 | P0 | Test whether direct distances match summed branch lengths in the reference tree | VAL-02, EMB-05 | The report shows errors and how they change with tree depth for both metrics |
| VAL-06 | P0 | Test whether embedding training has flattened distances near the tree tips | VAL-02, EMB-05 | Within-group effects and near-zero rates are compared with between-group controls |
| VAL-07 | P0 | Build the same subset tree once with embeddings and once with k-mers | TRE-09, VAL-02 | The comparison shows which topology and length differences come from the metric |
| VAL-08 | P0 | Turn the evidence into rules that control tree resolution and scaling | VAL-04, VAL-05, VAL-06, VAL-07 | The policy records approved ranks/depths, limits, metric, and evidence version |
| VAL-09 | P1 | Test a monotonic recalibration when embedding distance does not grow linearly | VAL-05 | Held-out accuracy improves without data leakage, or recalibration is rejected |
| VAL-10 | P1 | Compare average-vector and real-vector representatives at each rank | TRE-04, VAL-02 | Measured error supports the chosen method and fallback limit |
| VAL-11 | P1 | Choose what happens on untrusted deep branches: stay unresolved, use nominal lengths, k-mers, or a curated tree | VAL-08 | One fallback is selected and saved in the policy and configuration |
| VAL-12 | P1 | Write the scientific result, limitations, and continue/stop recommendation | VAL-08, VAL-11 | The report states where embeddings are reliable and whether further engineering is justified |

### WS5 - Integration, reliability, and scale engineering

| ID | Pri | Task | Depends on | Deliverable / acceptance |
| --- | --- | --- | --- | --- |
| INT-01 | P0 | Define one run configuration consumed by every stage | ARC-02 | A checked-in toy configuration drives the full pipeline without manual path edits |
| INT-02 | P0 | Implement orchestrated subset flow: ingest, backbone, embed/baseline, tree, validate, render | ARC-05, ING-08, EMB-05, TRE-09 | One command or documented command sequence completes the toy run |
| INT-03 | P0 | Add stage-level structured logging and consolidated run summary | INT-01 | Failures identify stage, artifact, record/taxon where applicable, and recovery action |
| INT-04 | P0 | Add end-to-end assertions for counts, IDs, checksums, topology, and finite non-negative lengths | INT-02 | Deliberately corrupted artifact makes the smoke test fail at the correct boundary |
| INT-05 | P0 | Publish the reproducible subset run and retain its manifest, outputs, and validation report | INT-02, VAL-08 | A clean environment reproduces the documented outputs |
| INT-06 | P1 | Add parallelism controls, resource limits, cancellation, and graceful checkpointing | ARC-07, TRE-13 | Constrained and interrupted runs terminate cleanly and resume correctly |
| INT-07 | P1 | Execute representative scale tests and identify the first CPU, GPU, memory, or I/O bottleneck | ING-11, EMB-07, TRE-15 | Measurements replace extrapolation for at least three dataset sizes |
| INT-08 | P1 | Produce a full-scale execution design with shard count, capacity, duration, storage, and cost assumptions | INT-07 | Every estimate cites a measured throughput and uncertainty margin |
| INT-09 | P1 | Add release checklist and artifact retention/versioning policy | INT-05, ARC-09 | Candidate release can be traced to source, code, model, config, and validation evidence |

### WS6 - Visualisation and communication

| ID | Pri | Task | Depends on | Deliverable / acceptance |
| --- | --- | --- | --- | --- |
| VIZ-01 | P1 | Define audiences and the questions each visual must answer | ARC-01 | Agreed storyboard covers method, scale, confidence, and biological result |
| VIZ-02 | P1 | Evaluate iTOL and existing renderers with exported clades | ING-10 | Selected tool preserves labels, lengths, and confidence annotations |
| VIZ-03 | P1 | Implement clade extraction by rank/name without loading avoidable data | TRE-14 | Requested genus/family/order export has the exact descendant tip set |
| VIZ-04 | P1 | Export iTOL annotation datasets for confidence, metric, suspect tips, and fallbacks | TRE-14, VAL-08 | Visual styles are generated from diagnostics, not manual editing |
| VIZ-05 | P1 | Produce static embedding-vs-k-mer and trusted-vs-untrusted comparison figures | VAL-07 | Figures state dataset, metric, rank/depth, and uncertainty |
| VIZ-06 | P1 | Produce the final subset-tree figure and pipeline architecture figure | VIZ-02, VIZ-04 | Figures are legible in slides and have reproducible source data |
| VIZ-07 | P2 | Investigate scalable whole-tree overview rendering | INT-07 | Recommendation documents practical limits; no custom viewer is built by default |

### WS7 - Diversity and curation applications

| ID | Pri | Task | Depends on | Deliverable / acceptance |
| --- | --- | --- | --- | --- |
| APP-01 | P2 | Define sample-by-tip abundance/input contract and unresolved-tip behavior | ARC-02 | Valid fixture and explicit missing-tip policy exist |
| APP-02 | P2 | Implement Faith's phylogenetic diversity | APP-01, TRE-14 | Hand-computed fixture matches expected branch union length |
| APP-03 | P2 | Implement unweighted and weighted UniFrac | APP-01, TRE-14 | Symmetry, identity, bounds, and hand-computed fixtures pass |
| APP-04 | P2 | Compare diversity conclusions across embedding, k-mer, and unscaled taxonomy trees | APP-02, APP-03, VAL-07 | Readout distinguishes metric effects from sample-composition effects |
| APP-05 | P2 | Define within-taxon distance/residual outlier score for curation | TRE-14 | Score has an interpretable threshold and excludes known unresolved deep nodes |
| APP-06 | P2 | Produce an auditable shortlist of suspect records/BINs | APP-05, ING-09 | Each candidate links to provenance and the evidence that triggered it |

### WS8 - Demo, documentation, and decision package

| ID | Pri | Task | Depends on | Deliverable / acceptance |
| --- | --- | --- | --- | --- |
| DEM-01 | P0 | Document setup, inputs, commands, runtime expectations, and troubleshooting | INT-02 | A new contributor completes the toy run from a clean checkout |
| DEM-02 | P0 | Capture the end-to-end subset result and key run statistics | INT-05 | Tree, report, manifest, and selected figures share one run ID |
| DEM-03 | P0 | Explain architecture decisions and the five prohibited failure modes | ARC-01 | Reviewers can trace each guardrail to implementation or test evidence |
| DEM-04 | P0 | Present validation honestly, including failed gates and deep-spine uncertainty | VAL-12, VIZ-05 | Claims do not exceed the trust policy's measured scope |
| DEM-05 | P0 | Produce the final recommendation: proceed, recalibrate, use a hybrid metric, or stop | DEM-02, DEM-04 | Recommendation cites quality, scale, cost, and remaining risks |
| DEM-06 | P1 | Create a full-scale engineering backlog from measured bottlenecks | INT-08, DEM-05 | Follow-on items are sized and ordered by dependency and risk |

## 9. Milestones and critical path

| Milestone | Exit criteria | Critical tasks |
| --- | --- | --- |
| M0 - Contracts frozen | Schemas, fixture, config, and source/model versions agreed | ARC-01 to ARC-04, ING-01, EMB-01 |
| M1 - Comparable metrics available | Canonical records have embeddings and k-mer signatures behind one interface | ING-02 to ING-08, EMB-02 to EMB-05 |
| M2 - Toy tree end to end | One post-order pass emits a valid scaled tree with diagnostics | TRE-01 to TRE-09, INT-01 to INT-04 |
| M3 - Trust boundary known | Three validation questions answered and policy consumed by traversal | VAL-01 to VAL-08, TRE-10 |
| M4 - Hackathon definition of done | Reproducible real subset, visual, scientific readout, recommendation | INT-05, VIZ-01 to VIZ-06, DEM-01 to DEM-05 |
| M5 - Stretch applications | PD/UniFrac and curation examples demonstrated | APP-01 to APP-06 |

The critical path is:

```text
Contracts and fixture --> Canonical ingest --> Embedding and baseline --> Distance providers
                                         |       |
                                         |       +--> Metric validation
                                         |                  ^
                                         v                  |
                                     Resolve and scale ---------+
                                              |
                                              v
Metric validation --> Trust policy --> Gated final tree --> Readout and recommendation
```

Work can proceed in parallel once M0 is complete: WS1 owns canonical data,
WS2 owns metric artifacts, WS3 develops against precomputed fixture vectors,
and WS4 prepares the reference mapping and preregistered tests. WS6 can evaluate
tools against the unscaled backbone, while WS7 remains off the critical path.

## 10. Quality gates and definition of done

### Engineering gates

- A clean environment can run lint, unit tests, and the toy end-to-end pipeline.
- All artifacts validate against their schema and checksum manifest.
- Input and output tip counts reconcile with explicit exclusions.
- The run is deterministic within documented floating-point tolerance.
- No code path materialises a global all-pairs matrix.
- Tree execution can resume from a valid subtree checkpoint.
- Output Newick parses successfully and contains only finite non-negative branch
  lengths.

### Scientific gates

- Embedding and k-mer metrics use the identical trimmed records and downstream
  algorithm.
- Depth-faithfulness, additivity, and tip-compression are reported by rank with
  uncertainty.
- The trust policy is generated from validation evidence and actually controls
  the final traversal.
- Deep or unsupported nodes remain soft or use the documented fallback.
- Results distinguish inferred facts, quality flags, and unresolved questions.

### Hackathon exit

The project is done for the week when a versioned run on a real, tractable BOLD
subset produces a resolved and scaled insect COI tree, machine-readable
diagnostics, embedding-vs-k-mer validation, a legible visual, and a concise
recommendation about metric quality and full-scale feasibility.

## 11. Main risks and responses

| Risk | Signal | Mitigation / owner |
| --- | --- | --- |
| Primer window mismatch | High `none` support or broad length distribution | Tighten/inspect gates and retain explicit exclusions; WS1 |
| Sampling bias | A few taxa dominate records or representatives | Within-taxon dedup and equal-child weighting; WS1/WS3 |
| Embedding is good for ID but not distance | Weak rank correlation, nonlinear path residuals, compressed tips | Calibrate, use k-mer/hybrid fallback, or narrow trust depth; WS4 |
| NJ invents unsupported deep structure | Unstable splits above trusted rank | Policy-gated soft bushes; WS3/WS4 |
| Giant fan-out exhausts memory/time | Local $k^2$ block exceeds budget | Approximate $\sqrt{k}$ bucketing and measured NJ limit; WS3 |
| Centroid leaves the embedding manifold | Parent distances degrade relative to medoid | Drift diagnostic and medoid fallback; WS3/WS4 |
| Taxonomy/vector mismatch | Missing or duplicate tip IDs at join | Fail-fast reconciliation report; WS1/WS3 |
| Approximate distances yield negative lengths | Clamp count or residual spikes | Record clamps, trigger NNLS, lower confidence; WS3 |
| Prototype cannot scale | Throughput or memory bends nonlinearly | Multi-size benchmarks and explicit capacity design; WS5 |
| Demo overstates evidence | Claims include failed validation depths | Bind visuals and narrative to versioned trust policy; WS6/WS8 |

## 12. Decisions to record

Create short decision records when each choice is made:

1. Canonical record identity and artifact format.
2. Exact DNABERT-S checkpoint, pooling, and vector normalisation.
3. Sourmash parameters and distance interpretation.
4. Centroid-drift threshold and medoid fallback.
5. NJ fan-out limit and pre-clustering method.
6. Bottom-up solver compatibility threshold and NNLS trigger.
7. Validated rank/depth trust boundary and deep-spine fallback.
8. Subset selection and full-scale compute/storage topology.
