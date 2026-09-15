---
title: Embedding tree validation
description: Tree comparison, embedding fidelity, replicate support and diversity sensitivity
---

## Purpose

Check that embedding distances are a faithful metric, not just a good identifier:
depth-faithfulness, additivity and tip compression against a k-mer baseline.
Compare the generated tree with an independently sourced phylogeny on the same
biological tip identities. A taxonomy backbone used during construction measures
structural consistency, not independent phylogenetic accuracy.

## Run a Known-Answer Check

```bash
uv run evospaice validate \
	--inferred tests/data/diversity_tree.nwk \
	--reference tests/data/diversity_tree.nwk \
	--mode rooted --length-mode raw \
	--inferred-units fixture --reference-units fixture \
	--units-evidence 'Identical synthetic fixture lengths' \
	--samples tests/data/diversity_samples.tsv \
	--output-dir results/validation-identity
```

Expected: RF zero, normalized RF zero, clade precision/recall one, branch-score
distance zero, and zero admissible diversity differences. This is a software
check, not a biological benchmark. Use a new output directory for each run;
existing nonempty directories require `--overwrite`.

`uv run python -m evospaice.validate.evaluate` accepts identical arguments.
Use `--help` for all options. For real inputs, supply the generated/reference
paths and declare their provenance. Select `--mode unrooted` when comparing
splits without an agreed biological root; diversity sensitivity requires
`--mode rooted` and compatible supplied study roots.

## Comparison Policies

* Exact unique leaf labels are required. `--taxon-map` accepts TSV columns
	`tree,label,taxon`, where tree is inferred, reference or baseline. Unlisted
	labels retain their identity. Many-to-one mappings fail rather than collapsing
	records, ASVs, BINs or species without a biological policy.
* `--taxa-policy strict` requires equal canonical sets. Explicit `intersection`
	prunes copies and reports exclusions. `--taxa-file` is a TSV with a `taxon`
	column selecting a benchmark set. A supplied baseline uses the same shared set.
* `--reference-kind taxonomy` labels a consistency check. Set
	`--reference-independence independent|backbone-derived|unknown` and provide
	citations, model and construction provenance in a `--metadata` JSON object.
	Independence is declared, not automatically verified. Holding out a clade
	requires withholding its constraints before construction, not pruning afterward.
* Unary nodes are normalized without losing path sums. Incoming root stems are
	ignored, but a basal path retained below the original study root after pruning
	remains relevant to rooted PD and branch-score comparisons.

## Metrics

RF uses DendroPy `symmetric_difference`. Precision/recall/F1 use informative
rooted clades or unrooted splits, excluding trivial tips/root and duplicate unary
representations. Normalized RF divides by the sum of informative counts in the
two trees; the denominator and convention are included in the report. Undefined
rates are null with reasons. Additional resolutions compatible with a reference
polytomy are distinguished from contradictions.

`--length-mode none` reports path correlations when lengths are valid, but no
absolute-unit errors. `raw` requires equal declared units and `--units-evidence`.
Embedding-derived lengths and substitutions/site are not automatically comparable.
`total-length` scales each aligned tree to total length one and labels the results
accordingly; it does not calibrate evolutionary units. Valid gated comparisons
report branch-score L2, weighted RF L1, path MAE/RMSE/bias, Pearson and Spearman.
Correlations are descriptive, without inappropriate independent-pair p-values.
Missing or invalid lengths leave topology usable and length metrics unavailable.

`--support-field label` or an annotation key, with `--support-scale fraction|percent`,
reads reference support. `--min-reference-support` is a fraction in [0, 1] and
collapses weak branches only in the topology view. Missing support on a branch
is an error when filtering. Branch-length and diversity comparisons retain the
original aligned trees because collapsing edges cannot preserve every path.

## Optional Diagnostics

`--distances` accepts a TSV with `taxon_a,taxon_b,embedding_distance` and optional
`kmer_distance`. Duplicate/reversed pairs, self-pairs, nonfinite values and
unknown IDs fail. A sparse table is allowed, with measured coverage reported.

Alternatively, `--embedding-vectors` accepts an NPZ containing a two-dimensional
numeric `vectors` array and a string `taxa` array matching the retained tips.
Pickles are disabled. Nonzero finite vectors are normalized and cosine distances
are queried only for selected pairs/quartets. Cosine distances can range from
zero to two. Exporting production FAISS bundles is a separate task.

* `--taxa-metadata` is a TSV with `taxon` and optional kingdom through species
	columns. It enables lineage-aware pair strata and within-species compression
	summaries; unknown identities do not form a shared species. Missing strata
	cannot support conclusions about that evolutionary depth.
* Reference path correlations are summarized globally, by taxonomic stratum,
	and, for rooted references, by reference MRCA-depth bins. Taxonomic ranks are
	not time, and gene trees need not equal species trees.
* `--embedding-fit --embedding-units UNIT --inferred-units UNIT` enables path
	residuals and normalized stress in the same declared distance units. For NPZ
	inputs UNIT must be cosine. This is in-sample reconstruction fit if those
	distances built the tree, not independent accuracy.
* Complete sampled quartets yield four-point additivity gaps; incomplete table
	quartets are counted as skipped. Tip-compression summaries report quantiles and
	zero fractions; `--near-zero-distance` adds an explicit unit-specific threshold.
* `--baseline-tree` scores a supplied k-mer tree under identical taxon/root/pair
	policies. Paired k-mer distances use the optional table column. Neither trees
	nor sketches are generated here; record their construction settings in metadata.
* `--replicates` accepts multi-tree Newick with `--replicate-kind` and a documented
	`--replicate-method`. Every replicate must contain the fixed benchmark taxa;
	extra taxa are pruned explicitly. Counts and frequencies are reported. Bootstrap
	support is repeatability under resampling, not truth; perturbations are labeled
	as such. Replicate generation is outside this package.
* `--samples` uses the diversity sample format. Strict sample coverage is the
	default; `--sample-taxa-policy intersection` records retained richness/mass and
	computes on the shared subset. Empty filtered samples remain in coverage and
	PD results; undefined beta comparisons carry reasons. PD errors are unit-gated,
	while normalized UniFrac differences are dimensionless.

## Outputs and Limits

`validation.json` records metric definitions, units, input hashes, versions,
provenance, root/mapping/pruning policies, coverage, selected pairs, seeds,
warnings and unavailable reasons. CSVs contain taxa, clades, pairs, diagnostic
strata and optional alpha/beta diversity comparisons. Optional CSVs have headers
even when empty, preventing stale outputs when a directory is reused.

Defaults: 5,000 tips, 50,000 pairs, 10,000 quartets, 1,000 replicates and seed
zero. `--max-tips`, `--max-pairs`, `--max-quartets` and `--max-replicates` override
them explicitly. Newick/table inputs are bounded at 32 MiB and NPZ decompressed
contents at 256 MiB. These are bounded-clade workflows, not million-tip or
out-of-core guarantees. Pair queries do not allocate a global taxon matrix.

Exit codes are 0 for report generation, 2 for invalid inputs/configuration,
1 for I/O errors, and 130 for interruption. A successfully generated report
with unavailable diagnostics is not a scientific pass.

## References

* [DendroPy tree comparisons](https://jeetsukumaran.github.io/DendroPy/library/treecompare.html)
* [DendroPy path distances](https://jeetsukumaran.github.io/DendroPy/library/phylogeneticdistance.html)
* [Diversity backend documentation](../diversity/README.md)
* [Implementation plan](../../../docs/diversity-tree-validation-plan.md)
