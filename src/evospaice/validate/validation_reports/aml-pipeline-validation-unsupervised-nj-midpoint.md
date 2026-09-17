---
title: Midpoint unsupervised NJ Azure ML validation run
description: AML validation of the supplied midpoint NJ tree, including provenance, coverage, RF distance and tip-to-root correlation
ms.date: 2026-09-17
---

## Run Summary

Azure ML pipeline `lime_cassava_s230jvxxd5` **completed successfully** on
2026-09-17. The evaluator took **612.0 seconds (10 min 12 s)** and produced
five JSON/CSV files. Completion means the metrics were computed, not that
the inferred tree passed a biological accuracy threshold.

The pipeline was created at 09:13:24.736 UTC, and its stream recorded child
completion at 09:28:52 UTC, an interval of about 15 min 27 s. The evaluator's
612.0-second duration excludes AML queue, setup and orchestration overhead.

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
and sufficient shared taxa. Both SHA-256 digests in the downloaded validation
JSON match the local inputs:

| Input | SHA-256 |
|-------|---------|
| Reference | `a23fcd828d1fe8db49be0434fb9d27f02e43c7afc28050e52f16d13bbac8cada` |
| Midpoint inferred | `3059728a67c9e72dc89830a940b386262e358bd0afb145183f3112df6377489b` |

## Coverage

| Tree | Original tips | Retained tips | Retained coverage | Excluded tips |
|------|--------------:|--------------:|------------------:|--------------:|
| Midpoint NJ | 246,729 | 61,600 | 24.97% | 185,129 |
| Reference | 91,376 | 61,600 | 67.41% | 29,776 |

The downloaded outputs confirm 214,905 excluded tips across both inputs,
360,160 original inferred nodes and 182,751 original reference nodes. The
retained tip identities exactly match those used in the
[previous original-NJ run](aml-pipeline-validation-unsupervised-nj.md).

The midpoint file contains every tip label from the original NJ file plus
**65,651 additional labels**. It is therefore not merely the same full tree
with a different root. Results may be compared on the shared subset, but
differences cannot be attributed solely to midpoint rooting. Rerooting alone
would leave unrooted topology unchanged when evaluated on the same taxa.

## Results and Timings

| Metric | Value |
|--------|------:|
| Raw unrooted RF | 65,568 |
| Normalized RF | 0.9999389983529555 |
| Observed informative split denominator | 65,572 |
| Shared informative splits | 2 |
| Inferred-only splits | 3,973 |
| Reference-only splits | 61,595 |
| Total inferred informative splits | 3,975 |
| Total reference informative splits | 61,597 |
| Spearman supplied-root tip-depth correlation | 0.048311233357985116 |

RF is **3,973 + 61,595 = 65,568**, normalized by
**3,975 + 61,597 = 65,572**. Only two informative splits match, indicating
almost no exact split agreement on the retained taxa. This is not a percentage
of incorrect taxa. The inferred tree has substantially fewer informative
splits than the reference, so RF reflects differences in resolution as well
as disagreements in resolved splits.

The split report is **byte-for-byte identical** to the previous original-NJ
run, not merely equal in aggregate RF scores. This supports unchanged unrooted
informative topology on the retained taxa, despite differences between the
full input files. The matched taxon identities and reference tip depths also
match exactly between runs.

Spearman correlation changed from **-0.004153686900401179** to
**0.048311233357985116**, an increase of approximately 0.05246. The midpoint
run shows a very weak positive association in supplied-root depth rankings,
not evidence of strong biological agreement. Original inferred depths use
the full supplied midpoint tree before pruning. The full files differ in
tip content, so this is not a controlled experiment isolating root placement.
No significance test or biological pass/fail threshold is reported. Branch
length units and reference independence are recorded as `unknown`.

| Evaluator stage | Duration |
|-----------------|---------:|
| Input checks and loading | 15.7 s |
| Taxa alignment, cloning, pruning and topology indexing | 553.9 s |
| RF topology and split-report computation | 37.3 s |
| Depths, correlation, hashing and output writing | 5.1 s |
| Total | 612.0 s |

Tree preparation accounted for approximately 90.5% of evaluator time and RF
for 6.1%. The original-NJ run took 462.1 s overall, with 412.3 s in preparation
and 37.6 s in RF. This midpoint run took 149.9 s longer overall and processed
more input tips and nodes; this is not a same-input performance benchmark.
Progress percentages represent stages, not elapsed-time estimates.

## Optimizations and Verification

The existing optimizations in [compare.py](../compare.py) are reused without
further code changes: single-pass taxon selection for pruning, precomputed
namespace mappings, a cached shared-split intersection and bytewise split-ID
decoding. Metric definitions, original-tree preservation and the split-ID
hash format are unchanged.

All **146 validation tests passed** in 17.73 seconds on this rerun's local
check, and Ruff passed for the evaluator comparison module and its tests.
No same-input before/after end-to-end performance benchmark was run.

Downloaded CSV counts reconcile with the JSON. Recomputing Spearman
correlation from the 61,600 paired depths reproduces the reported value.
Both input filenames and SHA-256 digests were checked against the requested
local files. The five outputs are stored separately from the original-NJ run.

Unrooted RF ignores branch lengths. Correlation uses original supplied roots
and excludes the root stem; matching tips does not establish comparable
roots or branch-length units. Completion does not establish biological
accuracy or downstream beta-diversity performance. See the
[metric definitions and caveats](../README_metrics.md).

## Artifacts

* [validation.json](../../../../results/validation-unsupervised-nj-midpoint/validation.json): metrics, warnings, versions and input hashes
* [taxa.csv](../../../../results/validation-unsupervised-nj-midpoint/taxa.csv): 338,105 input tip records with retention decisions
* [clades.csv](../../../../results/validation-unsupervised-nj-midpoint/clades.csv): 65,570 unique informative splits and their origins
* [node_lengths.csv](../../../../results/validation-unsupervised-nj-midpoint/node_lengths.csv): 542,911 original nodes
* [tip_to_root_correlation.csv](../../../../results/validation-unsupervised-nj-midpoint/tip_to_root_correlation.csv): 61,600 paired tip depths and ranks
* [Evaluator stdout](../../../../results/validation-unsupervised-nj-midpoint/job-logs/artifacts/user_logs/std_log.txt): stage timings and printed results

The five result files were downloaded using the existing Azure login from
the child output path verified in its logs:
`azureml://datastores/workspaceblobstore/paths/azureml/36cefe53-a25a-420c-81d1-e779a0ef91da/results/`.
Local result files follow the repository's existing ignored-output policy.
