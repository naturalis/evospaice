To match the tree with samples from the field we need a matching field.
The challenge is that the tree has tips that are only a sequence representing a cluster of sequences.

If we blast a sequence on BOLD and we get a list of possible matches (sequences) with there corresponding sequence ID. They might not exist in the tree! But closely related sequences are clusterd in Barcode Index Numbers (BINS). So if the tree contains the BIN for the choosen sequence in the tips AND the output of the BLAST contains the BINs for each sequence, we can build a match. 

IN the current state we do not have BINs in the embeddings and we do not have output containing the BINs.
We will therefore match on sequence id for now. This means that we need to prune the sample files to only contain data that have sequence ids that are represented in the tree.
