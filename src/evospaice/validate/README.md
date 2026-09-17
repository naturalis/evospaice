Check that embedding distances are a faithful metric, not just a good identifier: depth-faithfulness, additivity, tip-compression — vs the k-mer baseline.

# Stratified embedding vs sequence distance validation

In this validation experiment, we assess how distances in embedding space behave in 
relation to distances in sequence space. The outline of the experiment is as follows:

1. From an embedding tree, we subsample _N_ pairs of tips. Because we assume that distance
   behave differently at different distance classes, we do stratification here. The
   stratification is based on 'depth', i.e. node distance from the root in terms of number
   if intermediate nodes between the root and the node that connects the pair of tips.
2. For each selected pair of tips, we compute the patristic distance: the length of the
   path that connects the tips.
3. For each distinct tip, we lookup the raw sequence record from the BOLD data dump and
   align it against a hidden Markov model (HMM) of the barcode locus (COI-5P) and combine 
   all the alignments in a multiple sequence alignment.
4. For the same pairs of tips for which we computed the patristic distance we compute the
   pairwise sequence distance. This is not the raw edit distance, it is corrected for 
   certain molecular processes that are part of the process of sequence mutation.
5. We then plot the patristic distances versus the sequence distances and calculate 
   some diagnostic metrics.             

For this experiment we have the following files in this folder:

- [patristic_vs_seqdist.py](patristic_vs_seqdist.py) - this is the main script that 
  performs steps 1-4 described above.
- [plot_pairs.py](plot_pairs.py) - the script that makes the plot based on the tabular
  output of the previous script.
- [pairs_diagnostics.py](pairs_diagnostics.py) - script that computes further diagnostics
- [environment.yml](environment.yml) - a conda environment for the dependencies of the
  scripts, i.e. some bioinformatics Python packages and the `hmmer` tool that makes the
  alignments
- [COI-5P.hmm](COI-5P.hmm) - a HMM for the barcode marker cytochrome oxidase subunit I,
  sequenced from the 5' direction 
- [strat_validate_results](strat_validate_results) - a nested folder with exemple output
  files

Furthermore, the experiment needs the following input files:

- a BOLD BCDM TSV data package, being the source of the sequences
- an embeddings tree from which we compute the patristic distances. The labels of the tips
  in the tree need to correspond with the `process_id` field in the BOLD BCDM  

  