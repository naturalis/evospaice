---
title: Unsupervised NJ Azure ML validation run
description: Completed AML run, optimizations, timings, coverage, RF distance and supplied-root correlation for the original unsupervised NJ tree
ms.date: 2026-09-17
---

## Run Summary

Azure ML pipeline `nifty_zebra_jls17dgd68` **completed successfully** on
2026-09-17. The evaluator took **462.1 seconds (7 min 42.1 s)** and produced
five JSON/CSV files. Completion means the metrics were computed, not that the
inferred tree passed a biological accuracy threshold.

* [Completed pipeline in Azure ML](https://ml.azure.com/runs/nifty_zebra_jls17dgd68?wsid=/subscriptions/caeead51-e874-4122-ba0e-c3c601c862ca/resourcegroups/rg-ai-seq-h3-hack-e1lkzk/workspaces/mlws-ai-seq-hack-e1lkzk)
* [Evaluation step in Azure ML](https://ml.azure.com/runs/8f49c47a-2d79-4770-96bd-8ed8f4a08eb2?wsid=/subscriptions/caeead51-e874-4122-ba0e-c3c601c862ca/resourcegroups/rg-ai-seq-h3-hack-e1lkzk/workspaces/mlws-ai-seq-hack-e1lkzk)
* Job template: [aml-pipeline-validation-unsupervised-nj.yaml](../jobs/aml-pipeline-validation-unsupervised-nj.yaml), with the explicit input override below
* Reference: [pruned.tre.txt](../../../../data/pruned.tre.txt)
* Inferred: [unsupervised_nj_tree.tre.txt](../../../../data/unsupervised_nj_tree.tre.txt), not the midpoint-rooted variant
* Compute: one node of `cpu-species-split-dedicated`, `STANDARD_D16DS_V5`
* Runtime environment: Python 3.12, DendroPy 5.0.13, SciPy 1.17.1, with the pinned container image from the template
* Source snapshot: `1bb922a5-a5aa-4de9-bb35-f5c1ee986e63`, including the evaluator optimizations

The pipeline was created at 08:51:07 UTC; its stream recorded child completion
at 08:59:39 UTC. This interval was about 8 min 31 s. The evaluator's own
462.1-second duration excludes AML setup and orchestration overhead.

## Submission and Input Identity

The job template changed concurrently to select the midpoint-rooted input.
The initial pipeline `neat_cheetah_t2mgxghfq5` therefore used that variant and
was cancelled at 08:47:11 UTC. Its final AML state is `Canceled`, not an
evaluator failure. No results from that attempt are included here.

The concurrent template edit was preserved. The replacement was submitted
with an explicit override selecting the original NJ input requested for this
evaluation:

```bash
AZURE_EXTENSION_DIR="$PWD/.venv/azure-cli-extensions" az ml job create \
  --file src/evospaice/validate/jobs/aml-pipeline-validation-unsupervised-nj.yaml \
  --set inputs.inferred.path=../../../../data/unsupervised_nj_tree.tre.txt \
    'display_name=Unsupervised NJ RF and correlation validation' \
    'description=Compare unrooted topology and supplied-root depths for the original unsupervised NJ tree.' \
  --resource-group rg-ai-seq-h3-hack-e1lkzk \
  --workspace-name mlws-ai-seq-hack-e1lkzk
```

The command retains `--mode unrooted --taxa-policy intersection --rf
--tip-to-root-correlation --overwrite`. The downloaded JSON records these
SHA-256 digests, both verified against the local input files:

| Input | SHA-256 |
|-------|---------|
| Reference | `a23fcd828d1fe8db49be0434fb9d27f02e43c7afc28050e52f16d13bbac8cada` |
| Inferred | `f04029214959be16eebc925f6f1f45e82a5aee752cc297b89a6548cf94e45ae6` |

## Coverage and Timings

| Tree | Original tips | Retained tips | Retained coverage | Excluded tips |
|------|--------------:|--------------:|------------------:|--------------:|
| Inferred NJ | 181,078 | 61,600 | 34.02% | 119,478 |
| Reference | 91,376 | 61,600 | 67.41% | 29,776 |

Both metrics describe the **61,600 shared tips**, not either full tree.
Intersection alignment excluded 149,254 tips across the two inputs. Depth
measurement visited 185,076 original inferred nodes and 182,751 original
reference nodes; only matched tips entered the correlation.

| Evaluator stage | Duration |
|-----------------|---------:|
| Input checks and loading | 8.1 s |
| Taxa alignment, cloning, pruning and topology indexing | 412.3 s |
| RF topology and split-report computation | 37.6 s |
| Depths, correlation, hashing and output writing | 4.1 s |
| Total | 462.1 s |

Tree preparation accounted for approximately 89.2% of evaluator time; RF
computation accounted for 8.1%. Progress percentages represent stages, not
elapsed-time estimates.

## Results and Interpretation

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
| Spearman supplied-root tip-depth correlation | -0.004153686900401179 |

RF is **3,973 + 61,595 = 65,568**, normalized by
**3,975 + 61,597 = 65,572**. Only two informative splits match, indicating
almost no exact split agreement on the retained taxa. This is not a
percentage of incorrect taxa. The inferred topology is also much less
resolved: it has 3,975 informative splits versus the reference's 61,597.
RF combines differences in resolution with disagreements in resolved splits;
it does not isolate conflicting relationships from missing resolution.

Spearman correlation is essentially zero, indicating no meaningful monotonic
association in the supplied-root depth rankings for this run. Depths use
original, unpruned trees with the root stem excluded. Unrooted RF does not
make the supplied roots comparable, and this run did not midpoint-root
either input. Branch-length units and reference independence are recorded
as `unknown`. These results alone do not establish biological validity,
statistical significance, or downstream beta-diversity performance. No
biological pass/fail threshold was applied. See the
[metric definitions and caveats](../README_metrics.md).

## Optimizations and Verification

The changes in [compare.py](../compare.py) preserve metric definitions and
the split-ID hash format:

* Prune using taxon objects selected in one namespace pass, avoiding repeated label searches.
* Supply a precomputed taxon mapping during namespace migration.
* Compute the shared-split intersection once, not once per report row.
* Decode split bitmasks bytewise, avoiding a wide-integer shift for every namespace label.

All **146 validation tests passed** and Ruff passed for the edited Python
files. Regression coverage checks hash compatibility across byte boundaries,
escaped and Unicode labels, direct namespace mapping, and original-tree
preservation. A local 10,000-taxon benchmark with 110 sparse/dense split IDs
produced identical hashes in 0.0286 s versus 0.1640 s for the previous ID
implementation, approximately **5.7 times faster for that microbenchmark**.

The previous AZ2 report recorded 11,056.4 s overall and 9,486.6 s for RF.
Those figures are context, not a controlled optimization comparison: this
run uses a different inferred tree with substantially fewer informative
splits. A same-input before/after end-to-end benchmark was not run.
Preparation is now the dominant measured cost; profiling cloning and pruning
is the next performance investigation, not evidence of a metric failure.

Two Pylance diagnostics remain in unchanged code: the optional DendroPy seed
node annotation and SciPy's inferred `spearmanr` return type. The edited
logic has no new reported diagnostics, and the runtime checks above passed.

## Artifacts

* [validation.json](../../../../results/validation-unsupervised-nj/validation.json): metrics, warnings, versions and input hashes
* [taxa.csv](../../../../results/validation-unsupervised-nj/taxa.csv): retained and excluded identities
* [clades.csv](../../../../results/validation-unsupervised-nj/clades.csv): 65,570 unique informative splits and their origins
* [node_lengths.csv](../../../../results/validation-unsupervised-nj/node_lengths.csv): 367,827 original nodes
* [tip_to_root_correlation.csv](../../../../results/validation-unsupervised-nj/tip_to_root_correlation.csv): 61,600 paired tip depths and ranks
* [Evaluator stdout](../../../../results/validation-unsupervised-nj/job-logs/artifacts/user_logs/std_log.txt): stage timings and printed results

CSV counts reconcile with the JSON, and recomputing Spearman correlation from
the downloaded paired depths reproduces the reported value. The pipeline's
named-output download returned no files because its metadata lacked a
resolved path; the five files were retrieved using the existing Azure login
from the child output at
`azureml://datastores/workspaceblobstore/paths/azureml/8f49c47a-2d79-4770-96bd-8ed8f4a08eb2/results/`.
Local result files follow the repository's existing ignored-output policy.
