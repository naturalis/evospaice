# PHYLOGENETIC REFERENCE TREE
What it looks like and how to read it
Naturalis Dublin Hackathon context
┌── Species A ┌──────┤ │ └── Species B ──────────┤ │ ┌── Species C └──────┤ └── Species D
> **In one sentence** A phylogenetic reference tree is a branching, weighted diagram that represents how DNA sequences or organisms are related; its shape shows relationships and its branch lengths show distance or accumulated change.
*Prepared from the existing Naturalis hackathon explanation*
## 1. What does a phylogenetic reference tree look like?
A phylogenetic reference tree is usually drawn as a branching diagram. The endpoints (tips or leaves) represent species, organisms, or DNA barcode sequences. Internal junctions represent shared ancestry or inferred branching events.
```text
                 ┌── Species A
          ┌──────┤
          │      └── Species B
──────────┤
          │      ┌── Species C
          └──────┤
                 └── Species D
```
In this small example:
- Species A and Species B are closely related because they meet at a recent shared branch.
- Species C and Species D form another closely related pair.
- The A/B group is more distantly related to the C/D group.
> **Two things to read** Topology is the branching shape: who is grouped with whom. Branch length is the distance associated with each edge: how far apart the sequences or lineages are.
## 2. Taxonomic tree versus phylogenetic tree
The distinction is central to the Dublin hackathon. Naturalis already has taxonomic backbones: classification structures that say which genera belong to a family, or which species belong to a genus. The desired result is a resolved phylogenetic tree that adds a branching order and meaningful branch lengths.
| Taxonomic tree: what we have | Phylogenetic tree: what we want |
| --- | --- |
| Family X<br>├── Genus A<br>├── Genus B<br>├── Genus C<br>└── Genus D<br><br>All four belong to the family, but their branching order is unknown. | Family X<br>│    ┌── Genus A<br>├────┤<br>│    └── Genus B<br>│    ┌── Genus C<br>└────┤<br>     └── Genus D<br><br>The branching order is resolved and distances can be represented. |
## 3. What is an unresolved polytomy?
A taxonomic parent with several children but no known branching order is an unresolved node, or polytomy.
```text
        ├── A
Parent ─┼── B
        ├── C
        └── D
```
The proposed hackathon workflow attempts to resolve this into smaller binary splits, for example:
```text
             ┌── A
        ┌────┤
Parent ─┤    └── B
        │    ┌── C
        └────┤
             └── D
```
## 4. What makes the tree “scaled”?
A scaled tree contains meaningful branch lengths, not only a branching shape. A short path suggests a smaller distance; a longer path suggests a greater distance or more accumulated change, depending on how the tree is defined and validated.
```text
Species A ──0.10──┐
                  ├── shared branch
Species B ──0.15──┘

Species C ─────────────0.80────────────┐
                                       ├── more distant group
Species D ─────────────0.90────────────┘
```
| Information | What it tells the reader |
| --- | --- |
| Topology | Which sequences or organisms are more closely related. |
| Branch length | How much distance is associated with the edges or paths between them. |
## 5. How embeddings enter the hackathon approach
The proposed Naturalis approach turns each DNA barcode sequence into an embedding: a numerical vector. Pairwise distances between embeddings are then used to construct local trees without first aligning every raw sequence.
```text
DNA barcode sequences
        │
        ▼
DNA embedding model
        │
        ▼
Embedding vectors
        │
        ▼
Pairwise distances → distance matrix
        │
        ▼
Neighbor Joining
        │
        ▼
Local phylogenetic tree
```
## 6. Reading a distance matrix
For four local items, a distance matrix may look like this:
|  | A | B | C | D |
| --- | --- | --- | --- | --- |
| A | 0 | 0.2 | 0.8 | 0.9 |
| B | 0.2 | 0 | 0.7 | 0.8 |
| C | 0.8 | 0.7 | 0 | 0.1 |
| D | 0.9 | 0.8 | 0.1 | 0 |
The smallest distances suggest that A is close to B, while C is close to D. Neighbor Joining can use this local matrix to infer a branching structure and branch lengths.
## 7. What a large Naturalis-scale tree may look like
At larger scale, the same pattern repeats across many taxonomic levels and barcode records. The complete tree would be too large to read as one static diagram, so a researcher would normally inspect selected regions, groups, samples, or unusual branches.
```text
Reference tree
├── Order / large group A
│   ├── Family A1
│   │   ├── Genus A1a
│   │   │   ├── Barcode sequence 001
│   │   │   └── Barcode sequence 002
│   │   └── Genus A1b
│   └── Family A2
├── Order / large group B
│   ├── Family B1
│   └── Family B2
└── ... many more groups and barcode sequences ...
```
> **Practical visualisation point** The goal is not necessarily to show every endpoint at once. A useful interface may let researchers zoom, filter, annotate, compare samples, and inspect suspicious long branches.
## 8. Simple mental model
Think of the result as a Git-style branching history combined with a weighted distance map:
- The branching pattern shows relationship and grouping.
- The weighted edges show distance.
- The reference tree provides a shared structure onto which samples and barcode records can be placed.
> **Naturalis moonshot** Start with an unresolved biological classification tree and turn it into a resolved, weighted phylogenetic tree using distances derived from DNA embeddings.
## 9. The shortest possible explanation
A phylogenetic reference tree looks like a branching diagram with labelled tips. Nearby tips share recent branches; distant tips meet deeper in the tree. In a scaled tree, the lengths of the branches also carry meaning. The Dublin hackathon explores whether DNA embeddings can provide the distances needed to build those local branches at useful scale.
