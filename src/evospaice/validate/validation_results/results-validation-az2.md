---
title: AZ2 correlation-only validation results
description: Results and reproduction steps for the bottom-up tree comparison against the pruned reference
---

## Summary

The AZ2 run completed successfully with Spearman's rho of
**0.10022639571255496** across **61,381 shared tips**, taking **27.0 seconds**
in the supplied terminal log. RF topology comparison was disabled.

This is a weak positive association in supplied-root depth ordering: tips farther
from the reference root tend only weakly to be farther from the inferred root.
It is not strong agreement and does not mean that 10% of the topology is correct.
The score does not measure topology, pairwise evolutionary distances or beta
diversity, and does not establish the overall usefulness of embeddings.

## Results

| Measurement                                 | Result              |
|---------------------------------------------|---------------------|
| Spearman's rho                              | 0.10022639571255496 |
| Correlation status                          | `ok`                |
| Shared tips compared                        | 61,381              |
| Original inferred tips                      | 100,802             |
| Excluded inferred tips                      | 39,421              |
| Original reference tips                     | 91,376              |
| Excluded reference tips                     | 29,995              |
| Excluded tip records across both trees      | 69,416              |
| Original inferred nodes measured            | 282,702             |
| Original reference nodes measured           | 182,751             |
| RF topology comparison                      | Disabled            |
| Total runtime from the supplied log         | 27.0 seconds        |
| Taxon matching time from the supplied log   | About 0.8 seconds   |
| DendroPy version                            | 5.0.13              |
| SciPy version                               | 1.17.1              |

The saved [validation report](../../../../results/validation-az2/validation.json)
records the score, coverage, warnings, library versions and input hashes.
Node counts and timings above are reported in the supplied terminal log.
`ok` means that the correlation was defined and computed successfully, not that
the tree passed a biological quality threshold. Runtime is specific to this run.

## Reproduce

Run from the repository root, `/workspaces/ai-sequence-identification`, with
the project environment installed and both input files available. On a fresh
checkout, run `uv sync` first; `--no-sync` uses the existing environment without
updating dependencies. The original run used the library versions listed above;
a fresh dependency resolution may select different versions.

```bash
uv run --no-sync evospaice validate \
	--reference data/pruned.tre.txt \
	--inferred data/unified_taxonomic_tree_bottom_up.tre.txt \
	--mode unrooted \
	--taxa-policy intersection \
	--no-rf \
	--output-dir results/validation-az2 \
	--overwrite
```

The flag is `--no-rf` on one line; the line break in the pasted terminal command
was display wrapping. Expected score output:

```text
tip-to-root-correlation: 0.10022639571255496
```

> [!WARNING]
> `--overwrite` replaces reports in the specified directory. To preserve this
> run, use a new output directory and omit `--overwrite`. Overwriting does not
> remove stale outputs from previously enabled metrics.

Verify input identity before comparing reruns:

```bash
sha256sum data/pruned.tre.txt data/unified_taxonomic_tree_bottom_up.tre.txt
```

Expected hashes recorded by the run:

```text
a23fcd828d1fe8db49be0434fb9d27f02e43c7afc28050e52f16d13bbac8cada  data/pruned.tre.txt
2c820a323752c69cfd505397a2de8dd29916fe5b11add74fa68546d67fc417f6  data/unified_taxonomic_tree_bottom_up.tre.txt
```

## Interpretation Limits

* Taxon matching uses the intersection of exact, case-sensitive labels. No taxon
	mapping or genus selection was supplied; this is not a Papilio-only evaluation.
* Correlation measures original root-to-tip branch-length sums before pruning.
	The supplied root is zero and its stem is excluded. All original non-root
	edges, including excluded branches, are checked for valid lengths.
* `--mode unrooted` controls RF only. With RF disabled, it does not reroot the
	trees or make the correlation root-independent.
* Comparable biological roots have not been established. Different rooting
	choices can change the depth ordering and the resulting correlation.
* Branch-length units are `unknown` for both trees. Positive uniform rescaling
	does not change Spearman ranks, but biological comparability is not verified.
* Reference independence is `unknown`. No p-value, uncertainty interval or
	biological pass/fail threshold was computed.

The earlier AZ1 score was approximately -0.00415 on 61,600 shared tips. AZ2 is
numerically more positive, but the retained sets differ and root comparability
is unverified. These runs alone do not establish that AZ2 is a better phylogeny.
A controlled comparison should use the same taxa and justified rooting choices.

## Output Files

All four files are under `results/validation-az2/`, relative to the repository root:

* [validation.json](../../../../results/validation-az2/validation.json): score,
	coverage, provenance, warnings and input hashes
* [taxa.csv](../../../../results/validation-az2/taxa.csv): original and canonical
	labels, retention flags and exclusion reasons
* [node_lengths.csv](../../../../results/validation-az2/node_lengths.csv):
	supplied-root length sums for every original node in both trees
* [tip_to_root_correlation.csv](../../../../results/validation-az2/tip_to_root_correlation.csv):
	shared taxa, paired length sums and descending ranks with averaged ties

No `clades.csv` was generated because RF was disabled. See the
[metric documentation](../README_metrics.md) for calculation and input rules.

