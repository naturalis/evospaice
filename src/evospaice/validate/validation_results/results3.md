/workspaces/ai-sequence-identification/src/evospaice/validate/jobs/aml-pipeline-validation-az2-rf.yaml

uv run --no-sync evospaice validate \
  --reference data/pruned.tre.txt \
  --inferred data/unified_taxonomic_tree_bottom_up.tre.txt \
  --mode unrooted \
  --output-dir results/validation-mock-unrooted \
  --overwrite
  
  [mlws-ai-seq-hack-e1lkzk](https://ml.azure.com/?wsid=/subscriptions/caeead51-e874-4122-ba0e-c3c601c862ca/resourcegroups/rg-ai-seq-h3-hack-e1lkzk/providers/Microsoft.MachineLearningServices/workspaces/mlws-ai-seq-hack-e1lkzk&tid=8cd24984-0aa3-4fc5-b09b-4d6ecfaa58fb) 