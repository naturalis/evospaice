---
title: "Building external barcode reference trees for longitudinal phylogenetic diversity monitoring"
author:
  - "Kartik Awasthi^{1}"
  - "Guy Bertental^{2}"
  - "Colin Desmond^{2}"
  - "Oded Fischler^{2}"
  - "Victor Heijke^{3}"
  - "Dominika Kresa^{3}"
  - "Logambal Madhuanand^{3}"
  - "Anna Nikahava^{1}"
  - "Frixos Papadopoulos^{2}"
  - "Ron Shakutai^{1}"
  - "Unknown contributor (commit identity: Ubuntu)^{4}"
  - "Rutger Vos^{3,*}"
date: "2026-11-09"
bibliography: references.bib
link-citations: true
---

^{1} Independent contributor (affiliation not verified in repository metadata)  
^{2} Microsoft (inferred from commit email domains and project context)  
^{3} Naturalis Biodiversity Center, Leiden, The Netherlands  
^{4} Affiliation unknown (machine-local commit identity in git history)  
\* Senior author and corresponding author.

## Abstract

Environmental DNA and metabarcoding studies increasingly rely on phylogenetic diversity metrics such as Faith's PD and UniFrac, which require trees with branch lengths rather than only species lists [@faith1992pd; @lozupone2005unifrac; @taberlet2012metabarcoding]. We describe EvoSpaice, a pipeline that builds barcode-based reference trees by combining taxonomic backbone structure with sequence embeddings and local distance-based refinement. The key design choice is that the reference tree is constructed as a reusable external object, independent of any single multiplexed analysis run, so alpha and beta phylogenetic diversity can be tracked over time on a stable reference basis.

Current results are promising but limited. The repository documents successful large-scale ingest and embedding runs for insect COI records from BOLD [@ratnasingham2007bold], along with initial topology/length validation workflows. At the same time, stratified validation indicates distance saturation behavior at deeper divergences, which affects branch-length calibration and can bias PD interpretation. We therefore present this as a working research pipeline rather than a finished phylogenetic product.

## 1. Why external barcode trees are needed for metabarcoding

The immediate practical target is metabarcoding, not curation: analysts need to compare biodiversity signals across many samples, projects, and years. If each multiplexed sequencing run uses a run-local tree (or no tree), PD trajectories are not directly comparable because the phylogenetic frame keeps changing. An external reference tree solves this by providing one stable coordinate system for repeated sample placement and repeated alpha/beta PD computation.

This distinction is central for monitoring applications. Long-term monitoring asks whether communities are gaining or losing deep lineages, becoming homogenized, or shifting toward particular clades. Those questions require branch lengths anchored outside each run's local taxon list. Curation use cases are also relevant, but here they are secondary.

## 2. Position relative to current initiatives

Several major reference initiatives already demonstrate the value of common phylogenetic frameworks, mostly in microbial settings: Greengenes2, SILVA, and GTDB all provide standardized backbone resources for comparative analysis [@mcdonald2024greengenes2; @quast2013silva; @parks2022gtdb]. EvoSpaice is aligned with that idea but targets large-scale DNA barcoding data with a taxonomy-guided, embedding-assisted reconstruction strategy.

At larger taxonomic depth, community-scale synthesis projects such as Open Tree of Life and TimeTree provide complementary assets for topology and calibrated times [@hinchliff2015opentree; @kumar2022timetree]. We treat these as future integration targets for deeper branches rather than as direct replacements for barcode-informed shallow structure.

## 3. Aims of this project

The repository's declared aim is to build a scaled COI reference tree for insects by using taxonomy for global scaffold structure and embeddings for local resolution and branch scaling. Concretely, this project aims to:

1. Produce an external, reusable barcode reference tree with explicit branch lengths.
2. Keep the workflow scalable by avoiding global all-by-all distance matrices.
3. Quantify where embedding distances behave as usable phylogenetic distances and where they do not.
4. Make all supplementary artifacts, scripts, and outputs auditable in this public repository.

## 4. Pipeline overview

The implemented architecture has three main steps: (i) ingest/filter/crop sequence records, (ii) produce embeddings and index artifacts, and (iii) perform tree refinement and branch-length assignment in a post-order traversal using local Neighbor-Joining and bottom-up scaling inspired by Wei and Koslicki [@wei2024branchlengths].

![High-level EvoSpaice pipeline for building an external reference tree.](pipeline-overview.svg)

This design explicitly separates the reusable reference-building stage from downstream sample-level analyses. In operational terms, the tree is built once per reference release and reused across many later metabarcoding analyses.

## 5. Experiments and implementation status so far

The repository currently documents the following completed or partially completed empirical work:

- **Ingest/filter/embedding production runs**: a full Insecta filtering and embedding workflow over BOLD-derived Leray-window COI records, reporting ~6.98M embedded records and associated FAISS/Parquet outputs in the operations validation report.
- **Species-level partitioning runs**: deterministic sharded species bundle generation, including reconciliation checks for IDs and output file counts.
- **Tree overlap/pruning checks**: overlap reports showing retained shared tip sets between large reference and inferred trees, and a Papilio-focused subset extraction test.
- **Tree comparison tooling**: a reusable validator producing normalized Robinson-Foulds and tip-to-root rank-correlation outputs for inferred-vs-reference comparisons.
- **Distance-structure validation**: stratified patristic-vs-sequence-distance analysis (`pairs_strat.tsv`) with moderate global association (Pearson 0.452, Spearman 0.602 in the provided diagnostics script output) and evidence of flattening at high patristic bins.

These outputs are enough to demonstrate pipeline feasibility and to expose limitations, but not enough to claim a fully calibrated deep phylogeny.

## 6. Known limitations and failure modes

We emphasize five limitations that materially affect interpretation:

1. **Distance saturation at deeper divergence**: in current COI stratified checks, sequence-distance medians rise with patristic distance at shallow bins but flatten at high bins, consistent with saturation above roughly intergeneric scales in this workflow. This compresses deep branch-length contrast.
2. **Branch-length distortion under non-additive distances**: bottom-up branch assignment assumes distances are sufficiently tree-additive; when this is violated, negative-length pressure or over-smoothed internal lengths can appear.
3. **Potential over-resolution from local NJ**: binary resolution is always produced even when deep signal is weak, so unsupported deep structure can be over-interpreted.
4. **Run-to-run and release sensitivity**: documented outputs are tied to specific BOLD releases, seeds, and processing settings; they are not yet release-invariant benchmarks.
5. **Unknown/partial taxonomic metadata burden**: a large fraction of records route through unknown or shallow labels, which limits confidence in deeper placement.

Consequences for PD are direct: if deep branches are too short or too uncertain, alpha PD can be underestimated for phylogenetically broad samples, and beta PD (including UniFrac-like contrasts) can be biased toward shallow differences.

## 7. Future work

The immediate technical priority is a hybrid depth model:

- Use barcode-informed distances primarily for shallow and intermediate branches where validation supports them.
- Constrain deeper topology using Open Tree of Life synthesis structure [@hinchliff2015opentree].
- Calibrate deeper branch times/length scales using TimeTree age estimates [@kumar2022timetree].

In short, we do not expect barcode-only distances to be sufficient for robust deep scaling; deeper branch lengths should be anchored by data sources outside the barcode marker.

## 8. Generative AI use disclosure

This project used generative AI in two places:

1. **Software development**: coding work was performed using an AI-assisted "hypervelocity engineering" workflow (AI pair programming for implementation, refactoring, and boilerplate acceleration), with human review and repository-based validation.
2. **Manuscript drafting**: generative AI was used to help draft and edit this manuscript from repository artifacts and explicit author instructions.

AI assistance increases throughput but can introduce plausible-sounding errors; therefore, all claims in this document should be interpreted as tied to the cited literature and repository evidence, not to model output alone.

## 9. Data, code, supplements, and licensing

All supplementary materials for this reported research activity are in this GitHub repository (`naturalis/evospaice`), including scripts, reports, intermediate examples, and validation artifacts. As documented in the project README, source-code outputs of the main project workflow are released as public-domain outputs (CC0 1.0). This preprint should therefore be read as an open working report of an ongoing method-development effort.

# References

