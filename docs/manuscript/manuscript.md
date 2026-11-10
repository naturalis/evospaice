---
title: "How far do DNA barcode embeddings go as phylogenetic distances? Taxonomy-guided tree building from millions of insect COI barcodes"
author:
  - "Kartik Awasthi^1^"
  - "Guy Bertental^1^"
  - "Colin Desmond^1^"
  - "Oded Fischler^1^"
  - "Sharon Hart^1^"
  - "Arno Harteveld^1^"
  - "Victor Heijke^2^"
  - "Dominika Kresa^2^"
  - "Logambal Madhuanand^2^"
  - "Frixos Papadopoulos^1^"
  - "Anna Pershukova^1^"
  - "Ron Shakutai^1^"
  - "Rutger A. Vos^2,\\*^"
date: "2026-11-09"
bibliography: references.bib
link-citations: true
---

<!--
AUTHOR CHECKLIST, remove before submission:
- Add ORCIDs still missing (Desmond, Fischler), and the Microsoft unit and
  city for each Microsoft author (split affiliation 1 if they differ).
- Add an archive DOI for the release (Section 6).
-->

^1^ Microsoft Frontier Company  
^2^ Naturalis Biodiversity Center, Darwinweg 2, 2333 CR Leiden, The Netherlands  
\* Corresponding author: rutger.vos@naturalis.nl

**ORCID iDs:**
Kartik Awasthi <https://orcid.org/0009-0008-3241-0983>;
Guy Bertental <https://orcid.org/0009-0004-6333-3766>;
Sharon Hart <https://orcid.org/0009-0002-6946-9790>;
Arno Harteveld <https://orcid.org/0009-0005-9099-7979>;
Victor Heijke <https://orcid.org/0009-0002-8030-4364>;
Dominika Kresa <https://orcid.org/0009-0007-6892-8218>;
Logambal Madhuanand <https://orcid.org/0000-0002-1534-5234>;
Frixos Papadopoulos <https://orcid.org/0000-0002-4429-1562>;
Anna Pershukova <https://orcid.org/0009-0007-8725-8176>;
Ron Shakutai <https://orcid.org/0009-0002-6440-295X>;
Rutger A. Vos <https://orcid.org/0000-0001-9254-7318>

## Abstract

Phylogenetic diversity metrics need reference trees with meaningful branch lengths, but DNA barcode libraries now hold millions of sequences, far beyond what conventional phylogenetic inference can handle. We asked whether embeddings from DNA language models can stand in for phylogenetic distances at this scale. We embedded 6.98 million cytochrome *c* oxidase subunit I (COI) barcodes of insects from the Barcode of Life Data System with Omni-DNA in about 20 minutes on GPU hardware, without computing a global distance matrix. From Omni-DNA embeddings of Lepidoptera, we then built two trees: one by neighbour-joining constrained by the Linnaean taxonomy, the other by unconstrained k-means clustering followed by neighbour-joining. We compared both with a maximum-likelihood reference tree. On 61,381 shared tips the taxonomy-constrained tree had a normalised Robinson–Foulds distance of 0.79 to the reference, against 0.82 for a tree built from the taxonomy alone. The embeddings raised the share of reference splits recovered from 11% to 20%, but only 21% of the constrained tree's splits occurred in the reference, against 49% for the taxonomy-only tree. The unconstrained tree recovered almost no reference splits (normalised distance ≈ 1.00). On tip pairs stratified by the rank at which they diverge, distances on the embedding tree tracked reference distances among conspecifics (Spearman ρ = 0.62) but only weakly within genera (0.40) and not significantly between families. Simple *k*-mer and Kimura distances outperformed the embedding tree at every rank, and all distances compressed strongly at deeper divergences. Barcode embeddings therefore carry usable phylogenetic signal at shallow depths only. We argue that they are better used for placement and shallow resolution under an independently inferred, dated backbone than for building whole-database trees. Because they need no alignment, they are most promising for barcodes such as fungal ITS that are hard to align at database scale, a use our results motivate but do not yet test. We release all code and outputs openly.

**Keywords:** DNA barcoding, COI, ITS, alignment-free distances, phylogenetic diversity, DNA language models, embeddings, neighbour-joining, large-scale phylogenetics, metabarcoding

## 1. Introduction

DNA metabarcoding has made it practical to survey communities at broad spatial and temporal scales [@taberlet2012metabarcoding]. Many analyses still summarise those surveys as taxon counts or overlap measures that ignore how distantly related the detected lineages are. Phylogenetic diversity (PD) metrics such as Faith's PD and UniFrac, and phylogenetic generalisations of Hill numbers, capture that relatedness [@faith1992pd; @lozupone2005unifrac; @chao2010phylodiversity]. Applied to environmental sequencing, they can reveal community shifts that richness alone does not [@bik2012deepwater]. These metrics need a reference tree whose branch lengths are interpretable and that stays stable across the many runs of a monitoring programme. In microbial ecology, shared reference phylogenies such as SILVA, GTDB and Greengenes2 provide this [@quast2013silva; @parks2020gtdb; @mcdonald2024greengenes2]. For animal COI barcodes [@hebert2003barcodes], no comparable resource exists, even though the Barcode of Life Data System (BOLD) holds tens of millions of records grouped into Barcode Index Numbers (BINs) [@ratnasingham2007bold; @ratnasingham2013bin].

Inferring a tree from millions of single-locus sequences runs into well-known limits. Maximum-likelihood tools such as FastTree 2, IQ-TREE 2 and RAxML-NG scale to large alignments but not comfortably to millions of tips [@price2010fasttree; @minh2020iqtree2; @kozlov2019raxmlng]. Methods built for pandemic-scale data, such as UShER and MAPLE, exploit the very low divergence among viral genomes, which barcodes across a whole class do not share [@turakhia2021usher; @demaio2023maple]. The strategies that have scaled to hundreds of thousands of eukaryotic or microbial taxa share one approach: they constrain or divide the problem. They place sequences on a fixed backbone [@matsen2010pplacer; @barbera2019epang; @balaban2022apples2], refine a backbone tree in many independent subproblems [@balaban2024udance], or graft clade-level analyses onto a taxonomic or synthesis backbone [@antonelli2017supersmart; @smith2018seedplants; @chang2020tact]. For insects specifically, @chesters2017insecttree built a species-level tree from COI and other loci under backbone constraints. Our own earlier pipeline, Bactria, grafted maximum-likelihood family subtrees onto an Open Tree of Life backbone [@hinchliff2015opentree; @vos2023bactria].

DNA language models offer a different route. Models such as DNABERT-S, Omni-DNA, BarcodeBERT and BarcodeMamba map each sequence to a fixed-length vector in a single pass [@zhou2024dnaberts; @li2025omnidna; @millanarias2023barcodebert; @gao2024barcodemamba]. Nearest-neighbour search over these vectors identifies barcodes about as accurately as BLAST, at a fraction of the cost [@millanarias2023barcodebert]. If distances between embeddings also behaved like evolutionary distances, they could replace the alignment and the all-against-all distance matrix that limit tree building at scale. That would matter most for markers that are hard to align, such as the length-variable fungal ITS [@schoch2012its; @abarenkov2024unite]. Nothing guarantees this, however. These models are trained for retrieval or token prediction, not to reproduce distances on a tree, unlike methods such as DEPP and H-DEPP that learn embeddings with an explicit tree-distance objective [@jiang2023depp; @jiang2022hdepp].

Here we test how far off-the-shelf barcode embeddings can stand in for phylogenetic distances. During a three-day hackathon we built a pipeline that embeds all insect COI records in BOLD, and we used embeddings of Lepidoptera to build trees in two ways: with and without the Linnaean taxonomy as a constraint. We compared both trees with a reference phylogeny, and then compared distances between tip pairs across taxonomic ranks with conventional sequence distances. The pipeline scales comfortably, but the embeddings add little phylogenetic information beyond the genus level. We discuss what this implies for building barcode reference trees.

## 2. Methods

![**Workflow and evaluation design.** (A) Records from a BOLD public release are filtered and cropped to a primer window. (B) Each retained record is embedded independently; vectors are indexed rather than turned into a distance matrix. (C) Two tree-building strategies, with and without the Linnaean taxonomy as a constraint. (D) Trees and tip-pair distances are compared with a reference tree, using a taxonomy-only tree as a baseline and the taxonomy scaffold to assign each tip pair a divergence rank.](pipeline-overview.svg){#fig:pipeline width=100%}

### 2.1 Data and filtering

We used BOLD public data packages in BCDM-TSV format: the 27 March 2026 release for the embedding run and the 30 June 2026 release for the taxonomy scaffold and the Lepidoptera experiments. For the embedding run we kept COI-5P records of class Insecta. Each record was cropped to the Leray window [@leray2013primers], about 313 bp, by searching for the primer, first as an exact IUPAC match and then allowing up to two mismatches. On a sample of 100,000 Arthropoda records, the mismatch-tolerant search reduced the proportion of records without a primer match from 57% to 7%. Records without any match were kept uncropped and flagged. For the tree experiments we used one representative record per BIN of Lepidoptera, cropped to the same Leray window, choosing representatives within each taxon so that two taxa sharing an identical sequence window were never merged.

To provide a constraint, a baseline and rank labels, we built a taxonomy scaffold for all Arthropoda BINs in the 30 June release: 17,617,788 of 23,954,047 records, giving 1,138,906 BIN tips under 253,372 named internal nodes. Each BIN was attached to the last common ancestor of the taxa its records were identified as. That placed 4.9% of BINs above the rank of their most specific identification, and 48.8% of BINs attach directly to a family because none of their records were identified further.

### 2.2 Embedding

The insect production run used Omni-DNA-20M [@li2025omnidna] (Hugging Face checkpoint `zehui127/Omni-DNA-20M`, revision `3b64e6a5`). Inputs were truncated to 1,024 tokens and processed in batches of 256. Each record's vector is the attention-mask-weighted mean of the final hidden states (256 dimensions), cast to 32-bit floats and L2-normalised, so that inner products equal cosine similarities. Vectors were written to a FAISS index [@johnson2019faiss] with record metadata in Parquet, and then sharded into one index per species. The Lepidoptera BIN representatives used for tree building (181,078 records from the 30 June 2026 release) were embedded with the same model, checkpoint, pooling and normalisation. Throughout, the distance between two vectors is the cosine distance 1 − **u**·**v**.

### 2.3 Tree construction

**Taxonomy-constrained neighbour-joining.** Using the BOLD species, genus and family assignments, we built the tree from the bottom up. Within each species, we joined the records by neighbour-joining (NJ) [@saitou1987nj] on their pairwise cosine distances, as implemented in scikit-bio. Each species was then represented by the renormalised mean of its record vectors. Species centroids were joined by NJ within each genus, genus centroids within each family, and family centroids into a single backbone. Each level's subtrees were attached at the corresponding nodes of the level above. The assembled tree was rooted once at its midpoint, and the few negative branch lengths that NJ produced were set to zero. The tree includes only the 100,802 BIN representatives with a complete classification from order to species; the other 80,276 lacked one or more ranks. Above family level (subfamily, tribe, superfamily), the topology is determined by the embeddings alone.

**Unconstrained clustering and NJ.** As a contrast without taxonomic input, we partitioned the embeddings into 2,000 clusters with spherical k-means in FAISS (20 iterations). We then built an NJ subtree within each cluster, joined the cluster centroids by NJ into a backbone, attached the cluster subtrees to it and rooted the result at its midpoint (181,078 tips).

**Generalised hierarchical builder.** The repository also contains a more general implementation of the taxonomy-constrained approach, which joins records into species, species into genera, genera into families, families into orders and orders into a common root by local NJ, grafting each complete child subtree into the connector above it. It offers five ways to represent a taxon when it is joined at the next rank: the record-count-weighted mean of its record vectors, the medoid (the actual record with the smallest total cosine distance to all others in the taxon), a mean weighted by Gerstein–Sonnhammer–Chothia (GSC) weights [@gerstein1994gsc] computed on the taxon's subtree, a Gaussian summary compared by 2-Wasserstein distance, and the spherical Fréchet mean. Each local NJ problem is checked against a limit on the number of children, which stops the run rather than dropping records; a build over all Lepidoptera families required a limit of 1,800, because the largest group has 1,710 child representatives. These alternatives were implemented and checked on subsets during the hackathon, but the trees evaluated in this study were built with the procedure described above, and we did not compare the alternatives with the reference at full scale.

### 2.4 Reference tree and taxonomy-only baseline

As the reference we used the Lepidoptera tree produced by Bactria [@vos2023bactria] (91,376 tips labelled by BOLD process ID). Bactria partitions barcodes by family, infers a maximum-likelihood subtree for each partition from aligned COI with topologically constrained RAxML-NG searches [@kozlov2019raxmlng], and grafts these onto a backbone constrained by Open Tree of Life [@hinchliff2015opentree]. This reference is therefore *not* independent of our inputs: it is based on the same marker and respects much of the same taxonomy. Agreement with it measures consistency with a conventional COI phylogeny under taxonomic constraints, not accuracy against the true history.

To show how much agreement the taxonomic constraint alone provides, we built a taxonomy-only tree. For every reference tip that could be matched to a species (61,380 tips), we placed it in a polytomy under its species, nested in its genus, tribe, subfamily and family as recorded in the scaffold. This tree contains no information from sequences or embeddings.

### 2.5 Evaluation

**Topology.** Each tree was pruned to the tips it shares with the reference. We then computed the unrooted Robinson–Foulds (RF) distance [@robinson1981rf], normalised by the total number of informative splits in both pruned trees, using DendroPy [@sukumaran2010dendropy]. RF penalises missing resolution as well as conflicting splits, so we report the number of splits in each tree alongside it. We also report the Spearman correlation between tip-to-root distances in the two trees, for comparison with earlier runs, but we give it little weight because it depends on how each tree is rooted.

**Distances by divergence rank.** We sampled 1,000 tip pairs from the taxonomy-constrained embedding tree (`patristic_vs_seqdist.py --stratify`), stratified by the depth (in edges) of each pair's last common ancestor on that tree, so that deep and shallow pairs were equally represented. The pairs were therefore drawn from the tree under test and classified by taxonomic rank only afterwards. For each pair we recorded:

1. the patristic distance on the embedding tree;
2. the Kimura two-parameter (K2P) distance [@kimura1980k2p] between the two full-length BOLD sequences (not the Leray window used for embedding), after aligning them to a profile hidden Markov model of COI-5P with HMMER [@eddy2011hmmer] and using match states only;
3. an alignment-free *k*-mer distance (exact 12-mer sets, Mash-style transformation of the Jaccard index [@ondov2016mash]);
4. the patristic distance between the same two tips on the reference tree.

Using the scaffold, we classified each pair by the rank at which it diverges: same species, same genus, same family, or different family. Within each class, we measured how well each distance tracks the reference distance with Spearman's ρ. Because sampling spread the pairs evenly over the embedding tree's depths, the embedding-tree distances are evenly spread by construction while the reference and sequence distances are not. This does not bias correlations computed within a rank class, but it does mean that the pooled correlations over all pairs should be read with care. Of the 1,000 pairs, 417 had both tips in the reference tree and a resolvable divergence rank.

### 2.6 Implementation

The ingest, embedding and species-splitting steps run as Azure Functions that submit Azure Machine Learning jobs, with infrastructure defined in Terraform. Embedding used A100 GPU nodes (Standard_NC24ads_A100_v4). Tree building and evaluation are Python scripts using NumPy, SciPy, scikit-bio, FAISS and DendroPy. All code, configuration and run reports are in the project repository (Section 6).

## 3. Results

### 3.1 Embedding at scale

The class filter retained 6,979,067 insect records (3.3 GB of FASTA). The embedding job completed without errors in about 20 minutes, producing a 7.2 GB FAISS index and 346 MB of Parquet metadata. The record count, the count of unique vector identifiers and the identifier range (0 to 6,979,066) all agreed. Splitting by species produced 131,914 species bundles in eight shards with no failures. However, 4,983,941 records (71.4%) carried no species name and went to a single "unknown species" bundle. This share reflects how deeply BOLD records are identified, and it limits any method that relies on species-level taxonomy.

### 3.2 Topological agreement with the reference

Table 1 summarises the comparisons. The taxonomy-only baseline, which uses no sequence information, had a normalised RF distance of 0.82 on 61,380 shared tips. It recovered 11.2% of the reference's informative splits, and 48.7% of its own splits occurred in the reference; the remainder are mostly taxa that are not monophyletic in the reference. The taxonomy-constrained tree, on almost the same 61,381 tips, had a normalised RF distance of 0.79. Its four-fold greater resolution raised the share of reference splits recovered to 19.8%, but only 21.4% of its splits occurred in the reference. In other words, the embeddings resolved many nodes the taxonomy leaves open, and most of those resolutions disagree with the reference. The unconstrained tree shared only two informative splits with the reference among 61,600 shared tips. Its tip-to-root distances were uncorrelated with the reference (ρ = −0.004 when rooted as supplied and 0.048 when midpoint-rooted).

: Topological agreement with the Bactria reference tree, after pruning both trees to their shared tips. Tips: shared tips. Tree splits, Ref. splits: informative splits in the tree and in the reference. Recall: shared splits as a proportion of the reference's splits. Precision: shared splits as a proportion of the tree's splits. nRF: normalised Robinson–Foulds distance (0, identical; 1, no shared informative splits). ρ: Spearman correlation of tip-to-root distances. Constrained NJ: taxonomy-constrained neighbour-joining; Unconstrained: spherical k-means followed by neighbour-joining.

| Tree | Tips | Tree splits | Ref. splits | Shared | Recall | Precision | nRF | ρ |
|:----------------|------:|-------:|-------:|------:|------:|-------:|------:|------:|
| Taxonomy only | 61,380 | 14,043 | 61,377 | 6,844 | 11.2% | 48.7% | 0.819 | n/a |
| Constrained NJ | 61,381 | 56,718 | 61,378 | 12,146 | 19.8% | 21.4% | 0.794 | 0.100 |
| Unconstrained | 61,600 | 3,975 | 61,597 | 2 | <0.01% | 0.05% | 1.000 | −0.004 |

### 3.3 Distances across divergence ranks

On all 1,000 sampled pairs, K2P distance correlated moderately with patristic distance on the embedding tree (Pearson r = 0.45, Spearman ρ = 0.60). The relationship levelled off: across the two highest deciles of embedding-tree distance (0.25 to 1.17), median K2P distance stayed at 0.13 ([Supplementary Figure S1](../../src/evospaice/validate/strat_validate_results/pairs_strat.png)).

Comparing each distance with the reference tree separates the behaviour of the marker from that of the embeddings (Figure 2, Table 2). Within species, all three distances tracked the reference closely, although the embedding tree did so least well (ρ = 0.62, against 0.92 to 0.94 for the sequence distances). Within genera and within families, K2P and *k*-mer distances still tracked the reference (ρ = 0.67 to 0.76), whereas the embedding tree did so only weakly (ρ = 0.40 to 0.46). Between families, no distance was strongly associated with the reference, and only K2P reached marginal significance (ρ = 0.40, *p* = 0.05). Median distances show the same compression: from same-species to different-family pairs, median reference distance increased about ninefold (0.056 to 0.495), whereas median K2P and *k*-mer distances increased only about threefold (0.048 to 0.161 and 0.051 to 0.154).

![**Distances between tip pairs compared with the reference tree, by divergence rank.** Each point is a pair of Lepidoptera BIN representatives whose tips both occur in the reference tree (n = 417), coloured by the rank at which the pair diverges. (A) K2P distance on HMM-aligned COI. (B) Alignment-free *k*-mer distance (k = 12). (C) Patristic distance on the taxonomy-constrained embedding tree.](../../src/evospaice/validate/strat_validate_results/rank_stratified.png){#fig:ranks width=100%}

: Spearman correlation between each distance and the reference patristic distance, within classes of divergence rank. All correlations are positive; *p* values in parentheses.

| Divergence rank | Pairs | K2P | *k*-mer | Embedding tree |
|:------------------|-----:|-------------:|-------------:|-------------:|
| Same species | 75 | 0.94 (<10^−30^) | 0.92 (<10^−30^) | 0.62 (<10^−8^) |
| Same genus | 281 | 0.76 (<10^−50^) | 0.73 (<10^−40^) | 0.40 (<10^−11^) |
| Same family | 36 | 0.76 (<10^−6^) | 0.67 (<10^−5^) | 0.46 (0.005) |
| Different family | 25 | 0.40 (0.05) | 0.20 (0.3) | 0.29 (0.2) |
| All | 417 | 0.86 | 0.83 | 0.59 |

## 4. Discussion

### 4.1 Embeddings carry shallow phylogenetic signal but are not calibrated distances

Distances on the embedding tree were positively and significantly associated with reference distances within species, within genera and within families, and the embeddings almost doubled the share of reference splits recovered beyond what the taxonomy provides (Table 1). Off-the-shelf models that were never trained on phylogenetic objectives therefore capture a real part of the evolutionary signal among close relatives. As distances, however, they did not yet match a 12-mer Jaccard index on COI at any rank we examined, and their association with the reference weakened with depth.

The likely reason is the training objective. Previous work shows that nearest neighbours in such spaces match BLAST results at the species level [@millanarias2023barcodebert]. Language models trained for token prediction or retrieval need to place similar sequences close together, but nothing in their training requires the *amount* of separation to reflect the amount of evolutionary change, or the distances to be additive along a tree. Methods designed for that purpose train the embedding directly against distances on a tree [@jiang2023depp; @jiang2022hdepp]. Using a general-purpose model to estimate branch lengths therefore calls for either such a training objective or a calibration step. Agreement with BLAST for identification is not, by itself, evidence that an embedding is suitable for this.

Two features of our design probably made the embedding results worse than the embeddings themselves. First, the distances we evaluated are patristic distances on an NJ tree built from centroids of centroids, so they combine embedding geometry with errors from tree building and from averaging vectors. Averaging can move a representative away from any real sequence; the medoid and other representations in our generalised builder (Section 2.3) avoid this, but we have not yet evaluated them against the reference. Second, the embeddings were computed from the Leray window of about 313 bp, whereas the K2P and *k*-mer distances in the same comparison used the full-length barcodes (median 656 aligned sites), so the sequence distances drew on roughly twice as much sequence. Comparing raw cosine distances from several models, including barcode-specific ones [@millanarias2023barcodebert; @gao2024barcodemamba], on the same rank-stratified pairs, with sequence distances computed on the same window, is the obvious next experiment, as is running the same comparison on trees built with each of the alternative representations; our scripts support both.

### 4.2 The taxonomy carries the deep structure

The topological comparisons point the same way. Without the taxonomic constraint, the embedding tree recovered essentially none of the reference splits. With it, the embeddings added correct resolution: the share of reference splits recovered almost doubled compared with the taxonomy alone. They did so at a cost in precision, since most of the added splits conflict with the reference. The deep structure our trees share with the reference therefore comes mainly from the classification, and the embeddings partly resolved the polytomies it leaves open. Part of this agreement is built in, because the reference respects much of the same taxonomy. Conversely, half of the taxonomy-only tree's splits are absent from the reference, a reminder that taxonomic groups in BOLD are often not monophyletic on a COI tree, so a strict taxonomic constraint also imposes errors.

### 4.3 Saturation limits any single-marker distance at depth

The rank-stratified comparison also shows that the loss of signal at depth is not specific to the embeddings. Uncorrected and K2P-corrected COI distances compressed roughly threefold relative to the reference between conspecifics and pairs from different families. Between families, they barely tracked the reference at all. This is the expected signature of saturation in a short, fast-evolving protein-coding marker, especially at third codon positions. The reference partly corrects for it with model-based maximum-likelihood branch lengths and a taxonomic backbone. Because the reference is itself inferred from COI, the strong agreement of K2P within species and genera is partly circular. The informative comparison is between the distances on the same pairs: there, all distances lost most of their signal between families. A whole-database tree whose deep branch lengths come from barcode distances, whether embedded or not, would therefore compress deep branches. That would bias PD towards shallow turnover and underestimate the diversity of phylogenetically broad assemblages.

### 4.4 Markers that resist alignment

COI is in many ways the easiest case for conventional methods: it is protein-coding, nearly free of indels in most animals, and aligns readily against a profile model, as we did here. Its *k*-mer and alignment-based distances are therefore strong baselines, and embeddings have to compete with them on their own ground. Many other barcodes are much harder. The nuclear ribosomal internal transcribed spacer (ITS), the primary barcode for fungi [@schoch2012its], is non-coding and varies widely in length, and its sequences cannot be aligned reliably across distantly related fungi [@fouquier2016ghosttree]. UNITE, the reference resource for ITS, holds nearly 10 million sequences and organises them into about 2.4 million species hypotheses by clustering rather than by alignment [@abarenkov2024unite]. For such markers, any distance computed across a broad set of sequences is either alignment-free or depends strongly on alignment choices.

This is where the properties we have shown for embeddings matter most. Embedding needs no alignment, treats every sequence independently, and in our pipeline scaled to millions of records in minutes. Within the range where our COI results show signal, roughly within genera, an embedding of an indel-rich marker could therefore provide distances where a reliable multiple alignment is impractical at database scale. The appropriate design would mirror ghost-tree, which builds fungal reference trees for UniFrac by grafting ITS subtrees for groups of close relatives onto a backbone inferred from a more conserved marker [@fouquier2016ghosttree]. Embeddings could replace the per-group alignment step in that design and extend it to the full scale of UNITE. Fast-evolving spacers saturate even sooner than COI, so this case is strongest over short distances and depends on a backbone for everything deeper.

Whether embeddings outperform the established alternatives for ITS is an open question that our COI results cannot answer. The relevant competitors are alignment-free *k*-mer distances, which also tolerate indels and are accurate between closely related sequences [@zielezinski2019afbenchmark], and alignments within genera, where ITS is usually still alignable. The models we used were not trained on ITS. The rank-stratified design introduced here applies directly: repeating it on UNITE, comparing raw embedding distances from general and fine-tuned models with *k*-mer and within-genus alignment distances, would show whether embeddings earn a place in building reference trees for markers that resist alignment.

### 4.5 Implications for barcode reference trees

These results support a hybrid design that is already common in large-scale phylogenetics. Deep topology and branch lengths should come from a backbone that does not rely on barcode distances, such as Open Tree of Life for topology and TimeTree for divergence times [@hinchliff2015opentree; @kumar2022timetree]. Barcodes should resolve and scale only the shallow parts of the tree, roughly within genera, where their signal is strong. uDance builds and updates large trees by refining many small subproblems independently on a backbone [@balaban2024udance], and distance-based placement methods add new sequences to a fixed tree cheaply [@balaban2022apples2]. Both fit this design better than building a whole tree at once. Embeddings are attractive for several steps of such a design: fast identification, clustering records into the units that subtrees are inferred from, choosing representatives, placing new metabarcoding reads on an existing tree, and, for markers that resist alignment, providing the distances from which shallow subtrees are built. Our infrastructure for embedding millions of records in minutes is directly reusable for those purposes. We are now pursuing a design in which per-genus subtrees inferred from sequences are grafted onto a dated backbone, for COI as well as for ITS.

### 4.6 Limitations

Our evaluation is limited in several ways. The reference tree is not independent of COI or of the taxonomy. The tip-pair analysis rests on 417 pairs, with few pairs in the deeper classes. This follows directly from how the pairs were drawn: depth in edges on an NJ tree with nested centroid joins does not correspond to taxonomic rank, so stratifying by depth produced uneven rank classes (75, 281, 36 and 25 pairs). Sampling stratified by rank, or drawing pairs from the reference tree, would give a more balanced design. Each experiment used a single model, marker window and random seed, and we evaluated only COI, so the case for markers that resist alignment (Section 4.4) remains to be tested. The evaluated trees were built with the simplest representation, a mean vector, and the alternatives in Section 2.3 remain unevaluated. We did not use pre-clustering of very large polytomies (the generalised builder only refuses joins above a set size), least-squares branch-length fitting such as the bottom-up assignment of @wei2024branchlengths, or confidence measures for internal nodes. These might improve the trees but would not remove saturation. Finally, 71% of insect records lack a species name, which limits any method that uses species-level taxonomy as a constraint. Some of our hackathon results, including run-specific outputs and Azure workspace links, depend on transient cloud resources. The numbers reported here are those recorded in the run reports in the repository.

## 5. Conclusions

Off-the-shelf DNA language-model embeddings let us process every insect COI barcode in BOLD in minutes, without alignment. They capture phylogenetic signal among close relatives: distances on the embedding tree tracked the reference within species, and more weakly within genera. Beyond that they add little to what the taxonomy already supplies, and the COI marker itself saturates. For COI, simple *k*-mer and alignment distances remain the stronger choice at every depth we examined. Reference trees for barcode-based PD should take their deep structure and branch lengths from independent sources and use barcodes only at shallow depths. Within that range, embeddings are most promising for markers such as fungal ITS, where reliable alignment at database scale is impractical and a fast, alignment-free distance is most needed.

## 6. Data and code availability

All code, infrastructure definitions, run reports, validation outputs and the scripts that generate Tables 1 and 2 and Figure 2 are available at <https://github.com/naturalis/evospaice> [archive DOI to be added on release]. The analyses in Section 3.3 can be reproduced with `src/evospaice/validate/rank_stratified.py`, and the baseline in Table 1 with `src/evospaice/validate/taxonomy_baseline.py` followed by `src/evospaice/validate/evaluate.py`. BOLD public data packages are available from <https://boldsystems.org>. Trees, embeddings and derived outputs are released into the public domain (CC0 1.0). The Taxonium-based viewer in the repository is distributed separately under GPL-3.0.

## Author contributions

Contributions are given using the CRediT taxonomy.

**Kartik Awasthi:** Software, Visualization, Writing – review & editing.

**Guy Bertental:** Software, Validation, Writing – review & editing.

**Colin Desmond:** Investigation, Software, Visualization, Writing – review & editing.

**Oded Fischler:** Methodology, Software, Writing – review & editing.

**Sharon Hart:** Methodology, Software, Writing – review & editing.

**Arno Harteveld:** Conceptualization, Project administration, Writing – review & editing.

**Victor Heijke:** Methodology, Software, Writing – review & editing.

**Dominika Kresa:** Software, Validation, Visualization, Writing – review & editing.

**Logambal Madhuanand:** Formal analysis, Investigation, Methodology, Software, Visualization, Writing – review & editing.

**Frixos Papadopoulos:** Software, Validation, Visualization, Writing – review & editing.

**Anna Pershukova:** Project administration, Software, Visualization, Writing – review & editing.

**Ron Shakutai:** Conceptualization, Methodology, Visualization, Writing – review & editing.

**Rutger A. Vos:** Conceptualization, Data curation, Formal analysis, Methodology, Project administration, Software, Supervision, Writing – original draft.

## Competing interests

Kartik Awasthi, Guy Bertental, Colin Desmond, Oded Fischler, Sharon Hart, Arno Harteveld, Frixos Papadopoulos, Anna Pershukova and Ron Shakutai are employees of Microsoft, which develops the Azure cloud platform used in this study. The Azure compute used in this study was paid for by Naturalis Biodiversity Center. The other authors declare no competing interests.

## Funding

This project is supported by internal funding provided by the Naturalis sector Digital Solutions and Infrastructure.

## Use of generative AI

The authors used AI coding assistants to write and refactor parts of the software and documentation, and an AI assistant to help draft and edit this manuscript from the project's code, run reports and the authors' instructions. The authors checked all reported numbers against the repository and take full responsibility for the content.

## Acknowledgements

We thank Ann Corrao (Microsoft) for interesting discussions about applications in this domain and her generous hospitality at the hackathon. We also thank the BOLD team and the many contributors of public barcode records.

# References
