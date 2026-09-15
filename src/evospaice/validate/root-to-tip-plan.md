---
title: Root-to-node length and rank agreement implementation plan
description: Proposed optional branch-length sums and species-tip Spearman comparison alongside RF
---

## Scope and Assumption

Status: proposed, not implemented.

Interpret "sum lengths for each node" as the sum along the path from the
supplied root to that node. Compute a value for every node, but compare the
two trees using matching species tips only. Internal node labels such as X
do not establish correspondence between trees.

Confirm this interpretation before implementation. Summing all branches below
a node is a different metric, subtree total branch length, and is out of scope.
Pairwise tip-to-tip patristic distances are also out of scope.

Keep the existing RF calculation and default CLI behavior unchanged. Add this
metric as an explicit opt-in, not as a replacement for RF.

## Metric Definition

For a node v, define its cumulative length from the supplied root:

$$
L(v) = \sum_{e \in \operatorname{path}(\mathrm{root},v)} \ell(e)
$$

The root has value zero. Ignore any stem length attached to the root itself:
it is not an edge on the path from that root to a descendant.

For the retained canonical tip identities T, define root-to-tip rank agreement:

$$
\rho = \operatorname{Spearman}
\left((L_{\mathrm{reference}}(t))_{t\in T},
       (L_{\mathrm{inferred}}(t))_{t\in T}\right)
$$

Use the same sorted taxon order for both vectors and average ranks for ties.
Higher is better: +1 means the same ordering, 0 indicates no rank correlation,
and -1 means the reverse ordering. Do not produce a p-value: tips are not
independent observations of evolutionary history.

The score measures relative depth from the root, not pairwise separation or
topological accuracy. Equal root-to-tip values can occur in different topologies.
An ultrametric or otherwise constant vector makes the correlation undefined.

## Input and Root Policies

* Use stored branch lengths, not original embedding vectors or sequence distances.
  Fitted tree paths need not equal the original pairwise distances.
* Require explicit caller acknowledgement that supplied roots are comparable.
  Record this declaration without claiming automatic biological verification.
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
* Record branch-length units as provenance, defaulting to unknown. Reference
  lengths are not assumed to be edit distances or substitutions per site.
  Do not compare raw sums across trees as though their units were equivalent.

## Implementation Steps

### 1. Add the Calculation

Add a small length-metric module beside [compare.py](compare.py). Use an
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

Propose `--root-to-tip` to request the score and
`--roots-comparable` to acknowledge the root assumption. Reject an opt-in
without acknowledgement and reject acknowledgement without the opt-in.
Keep `--mode` dedicated to RF, including its existing report root policy.

Run the length traversal on original trees. Use retained rows from RF's
coverage table to translate original tip labels into canonical identities
and pair values. Do not reimplement taxon reconciliation independently.

### 3. Report Results

Add a `root_to_tip` object to the JSON report only when requested. Include
Spearman rho, compared-tip count, status, undefined reason when applicable,
supplied-root policy, caller acknowledgement, and branch-length provenance.
Record the SciPy version for enabled runs. Distinguish lengths ignored by RF
from lengths used by this metric; do not leave the report globally claiming
that all lengths were ignored.

Propose two optional CSV outputs:

* `node_lengths.csv`: tree, node ID, parent ID, original label, node kind,
  and root-to-node sum for every original node
* `root_to_tip.csv`: canonical taxon, reference sum, inferred sum,
  reference rank, and inferred rank for retained tips

Mark node IDs as local to each input serialization. Neither rows nor labels
imply that internal nodes correspond between trees. Keep CSV ordering
deterministic for the same inputs.

Advance the current report schema from 4 to 5 when implementing these changes,
with regression tests for both opt-in and RF-only runs. Preserve existing
topology fields. Print the additional score when requested while preserving
RF-only terminal output.

Extend existing input/output collision checks to both new filenames, including
symlink and hard-link cases. Compute and serialize all metrics before creating
output files. Continue recommending fresh output directories: `--overwrite`
does not clean up stale optional files from earlier runs.

### 4. Add Tests and Documentation

Extend [test_validate.py](../../../tests/test_validate.py) rather than creating
a separate suite. Use the existing mock fixtures and small inline Newick trees.

| Case | Expected result |
| --- | --- |
| Reference mock depths for A, B, C, D | 0.07, 0.08, 0.32, 0.35 |
| Inferred mock depths for A, B, C, D | 0.35, 0.08, 0.07, 0.32 |
| Mock tip rank correlation | -0.4 within floating-point tolerance |
| Same nonconstant tree twice | rho = 1 |
| Positive scaling of all lengths in one tree | Unchanged ranks and rho |
| Some tied depths | Average ranks, matching SciPy |
| One or both constant depth vectors | Null rho and explicit reason |
| Root stem length present | Root remains zero; stem excluded |
| Zero or invalid non-root edge lengths | Zero accepted; invalid inputs rejected |
| Mapping, selection, and intersection | Same retained canonical tips as RF |
| Pruning away one root child | Original root-to-tip sums preserved |
| Unrooted RF with length metric enabled | Original roots used only for depth score |
| Unary nodes and deeply nested trees | Correct sums without recursive traversal |
| Repeated or absent internal labels | Unique local node IDs; no label-based matching |
| RF-only invocation | Existing RF results and length-tolerant behavior preserved |
| Invalid opt-in or output/input collision | Exit 2 without new report files |
| Input tree objects and files | Unmodified by calculations |

Update [README.md](README.md) with the opt-in command, mock depth table,
undefined-score policy, output schema, and root/units caveats. Preserve all
existing external references. Clearly distinguish an input error from a valid
RF report with an undefined optional correlation.

## Verification and Completion

Run the focused validation suite and lint after implementation:

```bash
uv run --no-sync python -m pytest tests/test_validate.py
uv run --no-sync ruff check src/evospaice/validate tests/test_validate.py
```

Sync dependencies first if adding SciPy requires an environment update. Exercise
both RF-only and opt-in CLI paths using temporary output directories. Confirm
the mock values, JSON null handling, CSV correspondence, and unchanged RF
scores. No biological pass/fail threshold is proposed for this experimental
metric; root provenance and independent reference selection remain prerequisites
for interpreting its score.