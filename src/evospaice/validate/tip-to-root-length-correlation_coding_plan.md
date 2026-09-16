---
title: tip-to-root-length-correlation implementation plan
description: Proposed optional tip-to-root-length-correlation using Spearman ranks
---

## Scope and Assumption

Interpret "sum lengths for each node" as the sum along the path from the
supplied root to that node. Compute a value for every node, but compare the
two trees using matching species tips only. Internal node labels such as X
do not establish correspondence between trees.

Confirm this interpretation before implementation. Summing all branches below
a node is a different metric, subtree total branch length, and is out of scope.
Pairwise tip-to-tip patristic distances are also out of scope.

Preserve RF calculations, CLI defaults, and RF-only terminal output. Add this
metric as an explicit opt-in, not as a replacement for RF. All reports will use
schema version 5; optional metric fields appear only when requested.

## Metric Definition

For a node v, define its cumulative length from the supplied root:

$$
L(v) = \sum_{e \in \operatorname{path}(\mathrm{root},v)} \ell(e)
$$

The root has value zero. Ignore any stem length attached to the root itself:
it is not an edge on the path from that root to a descendant.

For the retained canonical tip identities T, define
`tip-to-root-length-correlation` as Spearman's rho of the tip-to-root lengths:

$$
\rho = \operatorname{Spearman}
\left((L_{\mathrm{reference}}(t))_{t\in T},
       (L_{\mathrm{inferred}}(t))_{t\in T}\right)
$$

Use the same sorted taxon order for both vectors and average ranks for ties.
Higher is better: +1 means the same ordering, 0 indicates no rank correlation,
and -1 means the reverse ordering. Do not produce a p-value.

The score measures relative depth from the root, not pairwise separation or
topological accuracy. Equal root-to-tip values can occur in different topologies.
An ultrametric or otherwise constant vector makes the correlation undefined.

## Input and Root Policies

* Use stored branch lengths, not original embedding vectors or sequence distances.
  Fitted tree paths need not equal the original pairwise distances.
* Before computing correlation, verify that both lists contain the same
  set of retained canonical tip IDs, with each ID appearing exactly once
  per list. Perform this check after taxon mapping, selection, and
  strict/intersection reconciliation. Reject mismatches or duplicates
  with an informative error. Align both vectors by the same sorted ID
  order before computing ranks and correlation.
* `tip-to-root-length-correlation` depends on the supplied root positions.
  Matching tip IDs does not establish biologically comparable roots.
* Allow RF to remain unrooted while this separate metric uses the original
  supplied roots. Never reroot either tree automatically.
* Require finite, nonnegative lengths on every non-root edge in each input tree.
  Accept zero; reject missing, negative, NaN, and infinite values. Reject
  non-finite cumulative sums, including overflow. Do not clip or impute lengths.
* Apply these extra checks only when the new metric is requested. Identify the
  offending tree and node in errors; perform all checks before writing outputs.
* Reuse existing taxon mapping, selection, strict/intersection rules, and coverage.
  Filter tip vectors to retained taxa, but measure from the original supplied
  root before any pruning or suppression can move that root.
* Record branch-length units as provenance using `branch_length_units.reference`
  and `branch_length_units.inferred` in the existing `--metadata` JSON object.
  Default each omitted unit to `unknown`; do not add new CLI flags.
  Do not compare raw sums across trees as though their units were equivalent.

## Implementation Steps

Keep all new metric implementation code inside
`src/evospaice/validate`.
Extend existing modules and reuse existing helpers first. Create a new script
or module only when absolutely necessary and no existing file is a suitable
home; explain the need before creating it. Do not add standalone runner scripts.
Keep regression tests in the existing test suite specified below; dependency
declarations may be updated in the existing project configuration if needed.

Use `tip-to-root-length-correlation` consistently as the metric's display name
and `--tip-to-root-length-correlation` as its CLI flag. Use
`tip_to_root_length_correlation` for Python identifiers and the JSON result key.
Root-to-node length remains the name of the underlying per-node calculation.

### 1. Add the Calculation

Add the calculation to an existing module such as [compare.py](compare.py),
following the file-reuse rule above. Use an
iterative preorder traversal of the original DendroPy tree: initialize root
depth to zero, then add each child edge length to its parent's cumulative value.
Avoid recursion and repeated root-path walks, especially for deep trees.

Return per-node records and a lookup of original tip label to root-to-tip value.
Use tree-local preorder indices for node IDs and parent IDs. Keep original
labels as descriptive fields, not cross-tree identifiers. Nodes need not have
labels; duplicate internal labels must not break the calculation.

Use SciPy's Spearman implementation rather than hand-written ranking. Check
existing dependencies and declare SciPy as a runtime dependency if needed.
Detect constant vectors before calling it. Return JSON null with an explicit
reason identifying the constant tree or trees, rather than NaN or a crash.
Require at least three matched tips for this planned score; the combined CLI
also retains RF's existing mode-dependent minimum and topology checks.

Traversal costs O(V) time and storage for V nodes; ranking costs O(T log T)
for T retained tips. Do not construct a pairwise distance matrix.

### 2. Integrate Without Changing RF

Update [evaluate.py](evaluate.py) to retain the loaded original trees instead
of passing a temporary dictionary directly into `prepare_trees()`.
That function deliberately removes lengths from its clones; do not change
this behavior to accommodate the new metric.

Use `--tip-to-root-length-correlation` to request the score without a
root-acknowledgement flag.
Keep `--mode` dedicated to RF, including its existing report root policy.

Run the length traversal on original trees. Use retained rows from RF's
coverage table to translate original tip labels into canonical identities.
Validate that both retained lists contain exactly the canonical IDs retained
by RF, each once. Reject mismatches or duplicates, then align values by sorted
canonical ID before computing correlation. Do not reimplement taxon
reconciliation independently.

### 3. Report Results

Add a `tip_to_root_length_correlation` object to the JSON report only when
requested. Include
Spearman rho, compared-tip count, status, undefined reason when applicable,
supplied-root policy and branch-length provenance.
Record the SciPy version for enabled runs. Distinguish lengths ignored by RF
from lengths used by this metric; do not leave the report globally claiming
that all lengths were ignored.

When `--tip-to-root-length-correlation` is enabled, write both CSVs below, including when the
correlation is undefined for otherwise valid inputs. Otherwise, write neither:

* `node_lengths.csv`: tree, node ID, parent ID, original label, node kind,
  and root-to-node sum for every original node
* `tip_to_root_length_correlation.csv`: canonical taxon, reference sum, inferred sum,
  reference rank, and inferred rank for retained tips

Mark node IDs as local to each input serialization. Neither rows nor labels
imply that internal nodes correspond between trees. Keep CSV ordering
deterministic for the same inputs.

Advance the report schema from 4 to 5 for all runs, with regression tests for
both opt-in and RF-only reports. Preserve existing topology fields; include
optional metric fields only when requested. Print the additional score when
requested while preserving RF-only terminal output.

Extend existing input/output collision checks to both new filenames, including
symlink and hard-link cases. Compute and serialize all metrics before creating
output files. Continue recommending fresh output directories: `--overwrite`
does not clean up stale optional files from earlier runs.

### 4. Add Tests and Documentation

Extend [test_validate.py](../../../tests/test_validate.py) rather than creating
a separate suite. Use the existing mock fixtures and small inline Newick trees.

| Case                                       | Expected result                                                         |
|--------------------------------------------|-------------------------------------------------------------------------|
| Reference mock depths for A, B, C, D        | 0.07, 0.08, 0.32, 0.35                                                  |
| Inferred mock depths for A, B, C, D         | 0.35, 0.08, 0.07, 0.32                                                  |
| Mock tip rank correlation                  | -0.4 within floating-point tolerance                                    |
| Same nonconstant tree twice                | rho = 1                                                                 |
| Positive scaling of one tree's lengths     | Unchanged ranks and rho                                                  |
| Some tied depths                           | Average ranks, matching SciPy                                            |
| One or both constant depth vectors         | Null rho and explicit reason; both CSVs written                           |
| Fewer than three retained tips             | Calculation rejects input; CLI exits 2 without new report files           |
| Root stem length present                   | Root remains zero; stem excluded                                         |
| Zero or invalid non-root edge lengths      | Zero accepted; invalid inputs rejected                                   |
| Cumulative-sum overflow                    | Informative error; exit 2 without new report files                        |
| Invalid lengths on excluded branches       | Rejected when metric enabled, before output writes                       |
| Mapping, selection, and intersection       | Same retained canonical tips as RF                                       |
| Matching IDs in different list orders      | Align by canonical ID; unchanged rho                                     |
| Mismatched, missing, or duplicate IDs       | Reject before correlation; CLI exits 2 without new report files           |
| Both lists omit the same RF-retained ID    | Rejected by comparison against RF's retained set                          |
| Pruning away one root child                | Original root-to-tip sums preserved                                      |
| Unrooted RF with length metric enabled     | Original roots used only for depth score                                 |
| Unary nodes and deeply nested trees        | Correct sums without recursive traversal                                 |
| Repeated or absent internal labels         | Unique local node IDs; no label-based matching                           |
| RF-only invocation                         | Existing RF results preserved; no optional fields or CSVs; schema 5       |
| RF-only inputs with invalid lengths        | Existing length-tolerant behavior preserved                              |
| Valid metric opt-in invocation              | Score and both CSVs produced; schema 5                                   |
| Supplied or omitted units metadata         | Per-tree units recorded; omitted units default to unknown                 |
| Output/input collision                     | Exit 2 without new report files                                          |
| Input tree objects and files               | Unmodified by calculations                                               |

Update [README.md](README.md) with the opt-in command, mock depth table,
undefined-score policy, output schema, units metadata fields, and root/units
caveats. Update its Purpose and Comparison Policies sections to describe RF as
topology-only and `tip-to-root-length-correlation` as optional. Clarify that lengths are
discarded only from RF working copies and preserved in the original trees for
the optional metric. Preserve all existing external references. Clearly
distinguish an input error from a valid RF report with an undefined optional
correlation.

## Verification and Completion

Run the focused validation suite after implementation. Ruff checks are not
required for this task:

```bash
uv run --no-sync python -m pytest tests/test_validate.py
```

Sync dependencies first if adding SciPy requires an environment update. Confirm
the mock values, JSON null handling, CSV correspondence, and unchanged RF
scores. No biological pass/fail threshold is proposed for this experimental
metric; root provenance and independent reference selection remain prerequisites
for interpreting its score.