---
title: Midpoint unsupervised NJ Azure ML validation run
description: AML validation of the supplied midpoint NJ tree, including provenance, coverage, RF distance and tip-to-root correlation
ms.date: 2026-09-17
---

## Run Summary

Azure ML pipeline `lime_cassava_s230jvxxd5` was submitted on 2026-09-17.
At report preparation, evaluation is running; final metrics and timings are
pending verification. No biological pass/fail threshold is applied.

* [Pipeline in Azure ML](https://ml.azure.com/runs/lime_cassava_s230jvxxd5?wsid=/subscriptions/caeead51-e874-4122-ba0e-c3c601c862ca/resourcegroups/rg-ai-seq-h3-hack-e1lkzk/workspaces/mlws-ai-seq-hack-e1lkzk)
* [Evaluation step in Azure ML](https://ml.azure.com/runs/36cefe53-a25a-420c-81d1-e779a0ef91da?wsid=/subscriptions/caeead51-e874-4122-ba0e-c3c601c862ca/resourcegroups/rg-ai-seq-h3-hack-e1lkzk/workspaces/mlws-ai-seq-hack-e1lkzk)
* Job definition: [aml-pipeline-validation-unsupervised-nj.yaml](../jobs/aml-pipeline-validation-unsupervised-nj.yaml)
* Reference: [pruned.tre.txt](../../../../data/pruned.tre.txt)
* Inferred: [unsupervised_nj_tree_midpoint.tre.txt](../../../../data/unsupervised_nj_tree_midpoint.tre.txt)
* Compute: one node of `cpu-species-split-dedicated`, `STANDARD_D16DS_V5`
* Environment: Python 3.12, DendroPy 5.0.13 and SciPy 1.17.1, with the pinned image in the job definition
* Uploaded source snapshot: `7f43f900-8ea3-4222-8bec-c20890e10af9`

The run reuses the optimized evaluator and the previous metric settings:
unrooted RF, intersection taxa policy, supplied-root tip-to-root correlation
and overwrite enabled. `force_rerun: true` requests a fresh execution. This
evaluator consumes the supplied midpoint file; it does not reroot the reference
or recompute midpoint rooting.

## Submission and Input Identity

Both input paths were explicitly supplied and verified in the submitted
pipeline bindings:

```bash
AZURE_EXTENSION_DIR="$PWD/.venv/azure-cli-extensions" az ml job create \
  --file src/evospaice/validate/jobs/aml-pipeline-validation-unsupervised-nj.yaml \
  --set inputs.reference.path=../../../../data/pruned.tre.txt \
    inputs.inferred.path=../../../../data/unsupervised_nj_tree_midpoint.tre.txt \
    'display_name=Unsupervised midpoint NJ RF and correlation validation' \
  --resource-group rg-ai-seq-h3-hack-e1lkzk \
  --workspace-name mlws-ai-seq-hack-e1lkzk
```

Local preflight verified unique leaf labels, finite nonnegative branch lengths
and sufficient shared taxa. The local input SHA-256 digests are:

| Input | SHA-256 |
|-------|---------|
| Reference | `a23fcd828d1fe8db49be0434fb9d27f02e43c7afc28050e52f16d13bbac8cada` |
| Midpoint inferred | `3059728a67c9e72dc89830a940b386262e358bd0afb145183f3112df6377489b` |

## Coverage

| Tree | Original tips | Retained tips | Retained coverage | Excluded tips |
|------|--------------:|--------------:|------------------:|--------------:|
| Midpoint NJ | 246,729 | 61,600 | 24.97% | 185,129 |
| Reference | 91,376 | 61,600 | 67.41% | 29,776 |

Local preflight found 214,905 excluded tips across both inputs, 360,160
original inferred nodes and 182,751 original reference nodes. The retained
tip identities exactly match those used in the
[previous original-NJ run](aml-pipeline-validation-unsupervised-nj.md).

The midpoint file contains every tip label from the original NJ file plus
**65,651 additional labels**. It is therefore not merely the same full tree
with a different root. Results may be compared on the shared subset, but
differences cannot be attributed solely to midpoint rooting. Rerooting alone
would leave unrooted topology unchanged when evaluated on the same taxa.

## Results and Timings

Pending completed-run artifacts and evaluator logs.

## Optimizations and Verification

The existing optimizations in [compare.py](../compare.py) are reused without
further code changes: single-pass taxon selection for pruning, precomputed
namespace mappings, a cached shared-split intersection and bytewise split-ID
decoding. Metric definitions, original-tree preservation and the split-ID
hash format are unchanged.

All **146 validation tests passed** in 17.73 seconds on this rerun's local
check, and Ruff passed for the evaluator comparison module and its tests.
No same-input before/after end-to-end performance benchmark was run.

Unrooted RF ignores branch lengths. Correlation uses original supplied roots
and excludes the root stem; matching tips does not establish comparable
roots or branch-length units. Completion does not establish biological
accuracy or downstream beta-diversity performance. See the
[metric definitions and caveats](../README_metrics.md).

## Artifacts

Pending download into the separate midpoint-run results directory.
