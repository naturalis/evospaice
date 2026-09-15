---
title: Workstreams
description: The four parallel workstreams for the EvoSpaice hack, with focus, staffing, prerequisites, and deliverables
author: EvoSpaice team
ms.date: 2026-09-15
ms.topic: overview
keywords:
  - workstreams
  - hackathon
  - team structure
  - deliverables
estimated_reading_time: 3
---

## Stream A: Frontend and user experience

How do users explore large phylogenetic trees?

* Team: 1 designer, 1 engineer, plus SMEs to interview.
* Prerequisites: mock data.
* Notes: evaluate different visualization packages for scalability.

Potential deliverables:

* Interactive tree visualization (mock data initially)
* User journey and storyboard
* Assets for the final video

## Stream B: Tree validation

How do we know the tree we built is a good tree?

* Team: 1 data scientist, 1 part-time data scientist (sounding board), 1 engineer, 1 SME.
* Prerequisites: reference tree (from Rutger's previous project).
* Notes: support Stream C with validation efforts.

Potential deliverables:

* Test datasets
* Validation metrics
* Evaluation code

## Stream C: Backend and tree construction

### Team 1: Embedding, partitioning, and clustering

Can we split sequences into independently solvable subsets?

* Team: 1 engineer, part-time data scientist, 1 SME.
* Notes: embedding generation code exists in the internal Naturalis repo. It would help to have embeddings in place before the hack.

### Team 2: Local tree builder

Construct trees for individual clusters: distance matrix calculation, tree construction, and potentially parallelization.

* Team: 1 to 2 engineers, part-time data scientist.
* Prerequisites: pick a starting scope, maybe one family or genus, or even one species.

Potential deliverables:

* Branch ordering
* Branch length estimation

### Team 3: Sub-tree merging and scaling

Merge local trees into larger structures.

* Team: 1 data scientist, 1 to 2 engineers.

> [!WARNING]
> Highest-risk technical area.

## Stream D: Demo and story

* Team: 1 TPM, 1 designer, part-time engineer.
