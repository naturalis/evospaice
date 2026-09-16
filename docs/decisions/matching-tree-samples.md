# Mapping samples onto the reference tree

The trees produced during the hackathon are based on sequence records whose embeddings were used in the divide-and-conquer algorithm. This means that these trees will have, at their tips, values of `process ID`, which reference the individual sequence. So the tips are not species or clusters. Furthermore, those IDs are selected out of a much larger corpus through a process of data reduction that involves filtering on taxonomic annotations and perhaps other criteria. As such, the tips stand in for larger clusters - BINs - that in turn are intended to correspond broadly with species.

Consequently, if we blast a sequence on BOLD and we get a list of possible matches (sequences) with their corresponding sequence ID, they might not exist in the tree. What we therefore need to do is collapse the sequence IDs from the matches to the BINs to which they belong, map the tips of the trees to their containing BINs, and match those.

However, in the current state we do not have BINs in the embeddings and we do not have output containing the BINs. We will therefore match on sequence id for now. This means that we need to prune the sample files to only contain data that have sequence ids that are represented in the tree.
