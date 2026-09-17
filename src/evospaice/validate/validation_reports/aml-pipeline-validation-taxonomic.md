---
title: AZ2 Azure ML validation run
description: Run outcome, timings, taxa coverage, RF distance and tip-to-root correlation for AZ2
---

## Run Summary

The validation script completed successfully in **11,056.4 seconds (3 h 4 min 16 s)**
and wrote five JSON/CSV report files, according to the supplied execution logs.
Completion confirms the metrics were computed, not that the inferred tree passed
a biological accuracy threshold. Azure ML queue and environment setup time are
not included in this logged duration.

* [evaluate - Azure Machine Learning](https://ml.azure.com/experiments/id/e012299b-de68-4511-9aa2-dbd85973ce26/runs/7583fd8b-2912-4928-86ed-ee85ac2c0825?wsid=/subscriptions/caeead51-e874-4122-ba0e-c3c601c862ca/resourcegroups/rg-ai-seq-h3-hack-e1lkzk/providers/Microsoft.MachineLearningServices/workspaces/mlws-ai-seq-hack-e1lkzk&tid=8cd24984-0aa3-4fc5-b09b-4d6ecfaa58fb)
* Job definition: [aml-pipeline-validation-az2.yaml](../jobs/aml-pipeline-validation-az2.yaml)
* Reference: [pruned.tre.txt](../../../../data/pruned.tre.txt)
* Inferred: [unified_taxonomic_tree_bottom_up.tre.txt](../../../../data/unified_taxonomic_tree_bottom_up.tre.txt)

The YAML enables unrooted Robinson-Foulds (RF) topology comparison and Spearman
tip-to-root correlation, retaining the intersection of taxon labels. It uses
`cpu-species-split-dedicated` and publishes the reports through the pipeline's
`validation_results` output.

## What Happened

The inferred tree contained **100,802 tips** and the reference **91,376 tips**.
Alignment retained **61,381 shared tips**, covering approximately 60.9% of inferred
tips and 67.2% of reference tips. It excluded 39,421 inferred-only and 29,995
reference-only tips, or **69,416 tips across both trees**. Both metrics therefore
describe the shared subset, not the full input trees.

* Input checks and tree loading: 12.3 s
* Taxa alignment and preparation for RF: 1,553.1 s (25 min 53 s)
* RF topology computation: 9,486.6 s (2 h 38 min 7 s)
* Depths, correlation, provenance and report writing: 4.4 s

RF computation accounted for approximately **85.8%** of logged runtime. The long
interval from 40% to 50% was the topology stage; progress percentages indicate
stages, not elapsed-time estimates. Depth measurement then visited 282,702
original inferred nodes and 182,751 original reference nodes, with correlation
computed for the 61,381 matched tips.

## Results and Interpretation

* Raw unrooted RF distance: 93,804
* Normalized RF distance: 0.7943029399810324
* Shared informative splits: 12,146
* Inferred-only informative splits: 44,572
* Reference-only informative splits: 49,232
* Spearman tip-to-root correlation: 0.10022639571255496

RF counts splits found in only one tree: **44,572 + 49,232 = 93,804**.
Normalization divides by the observed informative split total,
**56,718 + 61,378 = 118,096**, yielding approximately **0.7943**. On a scale where
0 means matching topology and 1 means no informative splits shared, this shows
substantial topological disagreement. It is not a percentage of incorrect taxa;
RF is sensitive to exact split matches and differences in tree resolution.

The correlation of approximately **0.1002** indicates a weak positive association
between the two rankings of root-to-tip branch-length sums. These depths use the
original supplied roots before pruning, even though RF is unrooted. Root
comparability is not established by this run, so the correlation alone does not
demonstrate biological agreement or disagreement. No significance test or
biological pass/fail threshold is reported. See the
[metric definitions and caveats](../README_metrics.md) for interpretation details.