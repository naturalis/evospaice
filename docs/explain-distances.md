
## Evolutionary divergence

Evolutionary divergence is measured by the branch lengths separating species from their most recent common ancestor.

Species A and Species B have a shared ancestor (x):
```text
 ┌── Species A (0.02)
─┤ (X)
 └── Species B (0.03)
```
Species A has an evolutionary distance of 0.02 to the (X) ancestor. So B is more diverged from the shared ancestor (X) since it has a larger distance.
 
Now consider this phylogenetic tree:
```text
         ┌── Species A (0.02)
 ┌──0.05─┤ (X)
 │       └── Species B (0.03)
─┤ (Z)
 │               ┌── Species C (0.12)
 └──0.20─────────┤ (Y)
                 └── Species D (0.15)
```
We can read from this graph:
- A + B have a shared ancestor X
- C + D have a shared ancestor Y
- A, B, C and D have a shared ancestor Z
- X is 0.05 away from Z
- Species A is 0.02 away from X
  
and we can calculate:
- Species A is 0.02 + 0.05 = 0.07 away from Z
- Species B is 0.03 + 0.05 = 0.08 away from Z
- Species C is 0.12 + 0.20 = 0.32 away from Z
- Species D is 0.15 + 0.20 = 0.35 away from Z

So D is most diverged from the shared ancestor (Z) since it has a largest distance.


## α-diversity
With α-diversity, we look at the diversity in a sample using the PD calculation. For this, we calculate Faith’s Phylogenetic Diversity (PD).

```
Faith’s Phylogenetic Diversity is the sum of all branch lengths needed to connect the species in the sample
where internal branches are counted once.
```

1. Consider sample S1 with only A + B. PD(A + B) =  0.02 + 0.03 + 0.05 = 0.10. _note the addition of the shared path to x_
2. Consider sample S2 with only C + D. PD(C + D) =  0.12 + 0.15 + 0.20 = 0.47.  _note the addition of the shared path to y_
3. Consider sample S3 with only A + D. PD(A + D) = 0.02 + 0.05 + 0.15 + 0.20 = 0.42. _note the addition of the shared path to x and y_

## β-diversity
With β-diversity, we look at the distance between samples. For this we use the UniFrac calculation (more ways exist, but this is widely used).

```
β-diversity (UniFrac) = unique branch length / total branch length
```

total branch length  = 0.02 + 0.03 + 0.05 + 0.12 + 0.15 + 0.20 = 0.57  
unique branch length takes only in consideration the branch lengths for the species _not_ in both samples.
So to calculate β(S1, S2) we determine shared paths

shared: A (0.02), X→Z (0.05) → shared = 0.07  
unique S1: B (0.03)  
unique S2: D (0.15), Y→Z (0.20) → 0.35  
So unique branch length = 0.03 + 0.35 = 0.38
β(S1, S2) = 0.38 / 0.57 ≈ 0.67

β-diversity in our example
|  | Sample 1 | Sample 2 | Sample 3 |
| -- | -- | --| -- |
| Sample 1 | - | 0.67 | 1 |
| Sample 2 | 0.67 | - | 0.33 |
| Sample 3 | 1 | 0.33 | - |

S2 vs S3 (~0.33): most similar (they share D and its clade).
S1 vs S3 (~0.67): moderately different.
S1 vs S2 (1.0): completely different—no shared branches. 


# In the light of the hackathon
In our project need to calculate the numbers for the species based on the embeddings given by our AI model.

Imagine the millions of species we have; this will create enormous possibilities in sample compositions and thus a very large multidimensional space if we use embeddings.

So we focus in this project on insects since they are well known, lots of sequences with high quality data: 
- We need build the tree (based on a taxonomic tree)
- We need to calculate the numbers (measure the distances)
- done
  
This will be large, massive and we need compute power. 
