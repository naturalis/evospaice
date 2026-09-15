# Moonshot: Building a Scaled Reference Tree from Barcode Embeddings

### A hackathon brief for engineers \- no biology background assumed

## What we're building, in one sentence

Take a large public database of DNA "barcode" sequences, embed each one with a fine-tuned **DNABERT-S/OmniDNA-20M** model, and use those vectors to turn a taxonomy into a **tree with meaningful branch lengths** — a structure that later lets us measure how biodiverse an environmental sample is and how different two samples are, using genetic distance rather than just counting species.

The deliverable for the week is deliberately narrow: **one tree, for one marker, for one group of organisms** — the *Leray-313 COI tree for insects*. Don't generalise beyond that. The scope is a given, not something to discover.

![IMage](/images/phylogentic_tree.png)

*Figure 1\. Fisheye projection of a [phylogenetic tree](https://en.wikipedia.org/wiki/Phylogenetic_tree) produced with [Walrus](https://www.caida.org/catalog/software/walrus/). Phylogenetic trees from DNA barcodes are directed, acyclic graphs where each external vertex (leaf, tip) is a barcode sequence, while the internal vertices (internal nodes) are hypothetical ancestors. Numerous tree-building methods exist that range from very sophisticated and computationally intense for small groups of species to crude methods designed to cope with very large numbers of input sequences. No good methods exist for the scale we target in this hackathon challenge, which is why this is such a moonshot\!*

## Why this is worth doing

Biologists collect an environmental sample (soil, water, a trap full of insects), sequence the DNA in it, identify the sequences against reference databases, and get back a list of species. Today they compare samples by comparing those lists — how many species, how much overlap. That throws away a lot: two samples might share *no* species yet be genetically almost identical, or share many, yet span wildly different branches of life.

The richer measure treats the sample as points on a **tree of genetic relationships** (fig 1\) and asks how much of the tree they cover and where. That needs a tree whose **branch lengths mean something** (genetic divergence), not just a branching diagram. Building that tree, at scale, from a messy real-world reference database, is the hard part — and it's what this hackathon attacks. Placing samples onto the finished tree and computing diversity numbers is downstream and out of scope this week.

## The one idea that makes this tractable

The naive approach — "build a tree from a few million sequences from scratch" — is a classic bioinformatics problem that does **not** scale and would eat the whole week. **We are not doing that.** The key move:

| The taxonomy gives the tree its rough shape. The embeddings resolve the shape within each group and scale every branch. |

Every record comes pre-labelled with a [**taxonomy**](https://en.wikipedia.org/wiki/Linnaean_taxonomy) (kingdom → phylum → … → genus → species). That hierarchy is already a tree — just a very unresolved, bushy one with no branch lengths. So we don't infer structure from scratch; we **take the taxonomy's topology as given** and use the embeddings only to (2) resolve the bushy parts and (3) put lengths on the branches.

This is the single most important thing to internalise. If you find yourself building a from-scratch phylogenetics engine, stop — you've left the plan.

## The one caveat that makes this *scientifically* interesting

We've already fine-tuned **DNABERT-S** and **OmniDNA-20M** models, and shown they **agree closely with BLAST** for identification. That is genuinely encouraging — but read carefully, because such agreement certifies the wrong property for what we're about to do:

| BLAST-agreement certifies the embedding as an *identifier* (retrieval: "the nearest vector is the right species"). The tree uses distances as a *scaling metric* (magnitudes and additivity across the whole tree). These are different properties. |

An embedding can be a perfect identifier and still be a distorted metric, because the contrastive objective it was trained with optimises for *separating* species, not for producing calibrated distances. Three specific things an identification benchmark cannot see, all of which our tree depends on — see the **Validate the distance** section, which is a first-class part of the week's work, not optional polish.

The upside: for the *shallow, within-clade* bulk of the tree — exactly the regime the BLAST validation covers — the embedding is probably an excellent distance, plausibly better than a [*k*\-mer](https://en.wikipedia.org/wiki/K-mer) approach. The risk is concentrated at the deep splits and at the very tips. We build on the embedding **and** we measure where it's trustworthy.

## Minimal glossary (the only biology you need)

* **Marker / barcode:** a short, standard stretch of DNA that acts like a species ID. Insects use one called **COI**. We're doing COI.  
* **Primer window:** the specific sub-region of the marker a given lab assay actually reads ("Leray-313" is one window of COI). Records were made by different assays, so they cover **different, partially-overlapping windows** — a source of pain; see Track 1\.  
* **Reference database:** a large public collection of barcode records (we'll use a [**UNITE**](https://unite.ut.ee/) release or a [**BOLD**](https://boldsystems.org/) data package). Each record \= sequence \+ taxonomy label. Expect millions of records, heavy sampling bias, and label errors.  
* **Taxonomy backbone:** the kingdom→species hierarchy attached to the records. We take its **topology at face value** — it's our tree's scaffold.  
* **Embedding:** a fixed-length vector produced by our fine-tuned models, where **distance between vectors is meant to track genetic relatedness**. One vector per record; that's the fingerprint everything downstream operates on.  
* **k-mer / sketch (baseline):** an older, alignment-free, purely-combinatorial way to get distances (sourmash/FracMinHash). Cheap, CPU-only, no training. We keep it as a **baseline to sanity-check the embedding against** — not the primary path.  
* **Distance:** a number for how genetically far two records are — here, **cosine (or Euclidean) distance between their embeddings**. Computed on demand from two vectors; fast.  
* **Polytomy:** a taxonomy node where many children hang off one parent with no structure between them (a genus with 500 species \= a 500-way "bush"). Resolving these is Track 2\.  
* **Neighbor-Joining (NJ):** a standard, fast algorithm that turns a small distance matrix into a tree. Used **locally**, one bush at a time.  
* **Medoid / centroid:** a group's single representative. With vectors we can use the true **mean vector** (centroid) — or the **medoid** (most-central real member) as a safe fallback. See Track 2\.  
* **Post-order traversal:** process all children before their parent. The backbone of Tracks 2+3 and the reason it scales.  
* **Branch-length assignment (the "paper"):** the Wei & Koslicki [paper](https://www.biorxiv.org/content/10.1101/2024.07.29.605688v2) solves our step 3 — given a fixed tree shape and distances between leaves, compute the branch lengths (Ax \= y). We reuse their **bottom-up method**.

## The pipeline at a glance

![](/images/pipeline.png)
*Figure 2\. Possible decomposition and division of labor for the hackathon into three tracks. Track 1 deals more with organizing the input DNA sequence data: trimming it, dereplicating it, computing embeddings. Tracks 2 and 3 deal with resolving the polytomies in the taxonomy tree and with assigning branch lengths. Two critical structural facts. **Tracks 2 and 3 are a single recursive pass, not two stages.** And **there is no global distance matrix** — Track 1 outputs vectors, and cosine distances are computed lazily inside the traversal, only for the pairs the tree structure actually needs. Materialising an all-pairs matrix (millions²) is the exact wall this design avoids.*

## Track 1 — Ingest & embed

**Goal:** turn a raw reference release into a clean, deduplicated set of records, each reduced to a vector. Think **ETL \+ batch inference**.

**Input:** a UNITE release or BOLD data package (sequences \+ taxonomy).  
**Output:** one **embedding per retained record**, plus each record's taxonomy label. *Not* a distance matrix.

**What needs to happen:**

1. **Restrict to the primer window.** Records aren't all the same sub-region and aren't guaranteed to be oriented the same way. Locate the target window (primer/pattern search), reverse-complement where needed, and **keep only records that cover the window** — non-covering records are dropped, not stretched. **Embed the trimmed window**, consistently, for every record.  
2. **Dereplicate — within taxon, never globally.** Collapsing thousands of near-identical copies of one species is the point (our main fix for sampling bias). But two *different* species can share an identical window; a global dedup would silently merge them into one mislabeled leaf. Dedup *inside* each taxonomic group.  
3. **Embed each surviving record** with a fine-tuned model checkpoint. This is GPU batch inference (Azure) — but embarrassingly parallel.

**Guardrails / gotchas:**

* **Do not compute all-pairs distances here.** Output is vectors. Distances are Track 2's business, on demand.  
* **Embed a consistent window.** A model-based vector of a Leray-313 fragment and of a full-length COI of the *same species* are not guaranteed to coincide. Trimming to one window first is what keeps embeddings comparable; don't embed whole records and hope.  
* Dereplication is a **design decision, not cleanup** — it's bias mitigation. This needs to be explicitly within-taxon.  
* Expect dirty labels: records identified only to a high rank ("Insecta"), or unplaceable ("incertae sedis"). Don't fix them here — carry them through **tagged**, so Track 2 can quarantine them off the deep spine.

**Good starting tech:** the fine-tuned model checkpoint \+ Azure GPU for inference; faiss if you want fast nearest-neighbour lookups; standard biopython FASTA parsing for ingest; sourmash to produce the k-mer baseline in parallel.

## Validate the distance *(parallel workstream — do not skip)*

This is a new approach relative to a k-mer pipeline as in the paper, and it is **load-bearing**, because BLAST-agreement doesn't cover it. Someone should own this from day one; it runs alongside Track 2 and **gates how much we trust the deep edges**. Take a clade where a trusted reference tree already exists and check three things the identification benchmark can't:

1. **Depth-faithfulness.** Do embedding distances preserve *rank order* against the trusted tree as you go deeper (species → genus → family → order)? k-mer distances fail *honestly* at depth — they hit a ceiling you can detect. Cosine also has a ceiling, but it degrades **smoothly and without a flag**, so it can hand you confident-looking deep distances from a region the model was never trained to resolve. We need to know where that starts.  
2. **Additivity.** The paper's method assumes leaf-to-leaf distance ≈ the *sum* of edge lengths along the path. Contrastive training warps geometry to enforce margins, which can make distances monotone-but-nonlinear in true divergence — topology stays right, but branch *lengths* (the whole point) get distorted. Test: reconstruct path-sum distances from the tree and compare to direct embedding distances.  
3. **Tip-compression.** Species-level contrastive training actively pulls same-species/same-genus members together. Great for ID, potentially bad for us: it can flatten intra-clade distances toward zero and **collapse the terminal branch lengths**, killing resolution exactly at the tips where most of Track 2's work happens. Test: are within-species / within-genus distances preserved or near-zero?

Run the **k-mer baseline through the identical downstream pipeline** as the control. Outcomes are all useful: if the embedding passes, make it the metric and you have a far stronger story than "we rebuilt a 2016 fingerprint." If it fails on additivity or tip-compression, either recalibrate the embedding distance toward additivity, or use embeddings for the shallow resolution and fall back to k-mers / a curated backbone for the deep lengths. The goal is to **find out inside the week**, not assume the transfer.

## Track 2 \+ 3 — Resolve & scale (one post-order pass)

**Goal:** walk the taxonomy from leaves to root; at each node, resolve its bush into a branching shape and assign branch lengths; summarise the node by one representative and carry it up. Think **recursive divide-and-conquer over a tree**, with a small NJ \+ small linear solve per node.

**Input:** vectors \+ taxonomy (Track 1).  
**Output:** the scaled reference tree — resolved topology with branch lengths.

**What happens at each node, bottom-up:**

1. **Gather the children's representatives.** Post-order guarantees every child is already reduced to one representative vector. A 500-way bush therefore deals only with its \~500 direct-child representatives — never the millions of leaves beneath. Cost is bounded by *fan-out*, not subtree size.  
2. **Compute the small distance block on demand.** Cosine among these children's vectors only. The only place distances are computed.  
3. **Resolve the bush with NJ** on that small block — flat fan-out becomes a branching sub-tree.  
4. **Assign this node's branch lengths** using the paper's **bottom-up method** (its Algorithms 1–2), which needs only these representative distances. Fuse this with step 3; don't build a second global stage.  
5. **Pick this node's representative** — the **mean vector** (centroid of the children's representatives), *frozen* — and carry it up. (Medoid is the safe fallback; see guardrails.)

**Guardrails / gotchas (this is where weeks get lost):**

* **NJ always returns a fully-resolved binary tree — even from noise.** At deep nodes the distances may be unreliable (per the validation), so structure NJ invents there can be fiction. **Gate resolution:** accept it only where distances support it; above a chosen depth/rank, leave the node a **soft bush**. With embeddings this matters *more* than with k-mers, because the unreliability is smooth and unflagged — lean on the validation findings and taxonomic depth, not on detecting a distance ceiling.  
* **The bush-size explosion is still real.** Post-order bounds *subtree* size, but a genus with thousands of species is a giant fan-out where NJ runs on thousands². **Pre-cluster the children into \~√k buckets** (cheap clustering on the vectors), resolve within, then across. Never hand a 5000-way node straight to NJ.  
* **Freeze the representative per node.** Choose it once, before the parent runs. If using the **mean vector**, watch for off-manifold drift — an average of vectors can land in a region no real sequence occupies, subtly poisoning distances above it (the vector analogue of the old "merged-sketch saturation" trap). If in doubt, use the **medoid** (a real member); it's always safe.  
* **Equal-weight the children** when forming the representative (one vote per child regardless of how many leaves it holds). Deliberate — stops an over-sequenced subclade from dragging the representative toward itself, extending Track 1's bias fix.  
* **Don't expect exact lengths, and clamp negatives.** Real distances aren't perfectly tree-compatible, so NJ and the paper's half-sums can go negative; clamp to zero. The paper's exact-recovery guarantees assume idealised conditions we won't meet — we're in its approximate regime by design. Its **NNLS** method (scipy.lsq\_linear) is the more robust fallback for badly-behaved subtrees.  
* **The deep spine is the least trustworthy output** — and with embeddings, dangerously so, because it can be *confidently* wrong rather than honestly saturated. Treat those lengths as low-confidence; prefer taking them from a curated backbone or nominal scheme over believing them from vectors. Spend accuracy budget shallow, where both the model and the signal are strong.

**Good starting tech:** any NJ implementation (scikit-bio, or a small custom one for the small blocks); scipy for the linear solve; the paper's reference code: [github.com/KoslickiLab/branch-lengths-assignment](http://github.com/KoslickiLab/branch-lengths-assignment) 

## Stretch goal — Score & visualise

If the scaled tree lands with time to spare: compute the diversity readouts (α \= within-sample, β \= between-sample, à la UniFrac / Faith's PD) on a couple of test samples, and render the "tree with a million tips" legibly. Treat this as **demo polish**, not core. Sample placement connects to separate Microsoft work on fast identification and is explicitly downstream; don't build it this week.

## The five ways to end up on the wrong track

1. **Building a tree from scratch from the sequences.** No — taxonomy supplies the shape.  
2. **Materialising a global all-pairs distance matrix.** No — vectors out of Track 1, cosine on demand in the traversal.  
3. **Trusting the embedding for scaling because it matched BLAST for ID.** No — that certifies retrieval, not metric quality; the Validate-the-distance checks are what license the scaling.  
4. **Resolving deep nodes fully with NJ.** No — gate resolution; leave deep nodes soft (and remember the embedding's deep unreliability is *hidden*).  
5. **Feeding a giant polytomy straight into NJ.** No — pre-cluster into √k buckets first.

If none of those five is happening, you're on the plan.

## Definition of done

* A prototype pipeline running end-to-end on a **subset** of a real UNITE/BOLD release (subset for tractability — full scale is later engineering).  
* Output: a resolved, branch-length-scaled tree for the insect-COI scope, built from DNABERT-S embeddings.  
* Validation results: where embedding distances are trustworthy (depth-faithfulness, additivity, tip-compression) and how they compare to the k-mer baseline.  
* A short readout: what worked, where the scaling/quality bottlenecks are, whether the embedding is the right metric or needs correction, how far it goes at full size, and whether it's worth engineering further.

![Pipeline](/images/pipeline.png)
