# Unified Bottom-Up Phylogenetic Tree Construction

A Python pipeline that builds a massive, biologically compliant phylogenetic tree from sequence embeddings. It combines hard taxonomic rank constraints with soft, data-driven distance calculations using **Neighbor-Joining (NJ)** clustering at every level of the biological hierarchy.

---

## Overview

Constructing phylogenetic trees directly from high-dimensional sequence embeddings (e.g., DNABERT) across thousands of specimens can be computationally expensive and may produce topologically erratic trees if unconstrained. 

This script solves this by enforcing a **Taxonomy-Constrained Bottom-Up Agglomerative Pipeline**:
1. **Sequences $\rightarrow$ Species:** Sequences are grouped within their assigned species using Neighbor-Joining on sequence embeddings.
2. **Species $\rightarrow$ Genus:** Species centroids are computed and clustered via NJ to form genus subtrees.
3. **Genus $\rightarrow$ Family:** Genus centroids are computed and clustered via NJ to form family subtrees.
4. **Family $\rightarrow$ Global Backbone:** Family centroids form the global tree backbone via NJ, followed by global midpoint rooting.

This hybrid approach ensures **100% strict adherence** to established higher-rank taxonomy (Family $\rightarrow$ Genus $\rightarrow$ Species) while allowing AI embeddings to dictate fine-grained evolutionary relationships within ranks.

---

## Technical Features

* **Distance Metric:** L2-normalized Cosine distance ($1.0 - \vec{u} \cdot \vec{v}$) across all embedding ranks.
* **Algorithmic Consistency:** Replaces rigid molecular clock assumptions (e.g., UPGMA) with relaxed-rate Neighbor-Joining (`skbio.tree.nj`) across every rank.
* **Grafting Architecture:** Subtrees are recursively constructed bottom-up and attached at respective taxonomic internal nodes.
* **Single Global Rooting:** Local subtrees remain unrooted during assembly to prevent branch length distortion; a single `.root_at_midpoint()` pass is applied to the final unified structure.
* **Visualization Compatibility:** Outputs sanitized Newick strings and tab-separated metadata tables compatible with **Taxonium**, **iTOL**, and **FigTree**.

---

