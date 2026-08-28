# Moonshot: Building a Scaled Reference Tree from Barcode Embeddings

## Documentation specific to the project

- [Slides that explain the why and how at high level](https://docs.google.com/presentation/d/1tmwUtHtdYxmklvtVXBrXGwielnjqg3Fat19jX08IHeE/edit?slide=id.g3f408b13edb_0_72#slide=id.g3f408b13edb_0_72)
- [A video where Rutger presents the slides](https://drive.google.com/file/d/1zPuKvw2lG_GrZrBRYMykWRFMUIKNMRUW/view?usp=drive_link)
- [A more detailed written explanation](https://docs.google.com/document/d/1eGodZDiN99KipS9K5rlrF06mjwaA8Q6nbJy5c8QP26U/edit?tab=t.0)

## Prior art, relevant background 

- [A repo where Naturalis did a prior attempt for COI](https://github.com/naturalis/barcode-constrained-phylogeny). What we learned here is that we can't simply pick one taxonomic level, solve at that level, and then stitch together. It needs to be more recursive.
- [A repo where compsci students and Naturalis did another prior attempt, for ITS](https://github.com/naturalis/MDDB-phylogeny). What we learned here is that scalable, alignment-free, distance-based approaches are tractable, but need taxonomic guidance to improve quality.
- [A preprint about assigning branch lengths to fixed tree shapes](https://www.biorxiv.org/content/10.1101/2024.07.29.605688v2). What we can take from this is inspiration for how to get branch lengths on taxonomic backbones from large reference databases. This preprint also has a [repo](https://github.com/KoslickiLab/branch-lengths-assignment).
