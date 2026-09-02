This is where we put the public reference data. *.tre files are produced from BOLD BCDM-TSV files using the tsv2newick script in src/ingest.

# The Arthropoda BIN tree

`outfile.tre.gz` is a taxonomy-derived tree of every BOLD BIN in phylum
Arthropoda. It is not a phylogeny. It is a scaffold: a topology taken from the
Linnaean classification attached to the records, meant to be resolved further
and given branch lengths from sequence data.

Generated with [`bcdm2tree.py`](bcdm2tree.py) from a BOLD public data package in
BCDM-TSV format:

```
python3 bcdm2tree.py -i BOLD_Public.tar.gz -t phylum:Arthropoda -l BIN \
    -o outfile.tre -s outfile.tsv -d dissolved.tsv
```

Of 23,954,047 records in the dump, 17,617,788 were used. The rest were outside
Arthropoda (3,126,464) or had no BIN assigned (3,209,795).

## Format

One Newick statement, no branch lengths, terminated by a semicolon. Gzipped.

**Every label is single-quoted**, because every label contains a colon: tips are
BIN URIs like `BOLD:AAA0001` and internal labels are rank-prefixed like
`genus:Vanessa`. The colon is part of the name, not a branch length separator. A
parser that splits on `:` without honouring quotes will silently mangle this
file rather than fail on it, so use a real Newick parser.

Tips carry annotations as bracketed comments in the FigTree/BEAST dialect:

```
'BOLD:AAA0001'[&rank=BIN,records=3,n_lineages=1,taxa=species:Vanessa atalanta,counts=3,placed_at=species:Vanessa atalanta]
```

NHX is deliberately not used. Its field separator is the colon, which occurs in
every value here, and both DendroPy and Biopython corrupt such values silently
rather than raising. The comma-separated dialect above survives colons and
spaces intact.

## What the nodes are

**Tips are BINs**, one per BIN, 1,138,906 of them. The label is the bare BIN URI
so it can be matched directly against sequence data. Its rank travels in the
`rank` annotation instead of the label.

**Internal nodes are taxa**, 253,372 of them, labelled `rank:name` at every
Linnaean level BOLD records: kingdom, phylum, class, order, family, subfamily,
tribe, genus, species, subspecies. Monotypic taxa are kept as unbranched nodes,
so a node's depth is meaningful.

**A tip's depth varies, and its parent is not necessarily a species.** Two
things push a tip up the tree:

1. *No identification.* Most BOLD records are not identified to species. If a
   BIN's records only ever named a family, the BIN hangs off that family.
2. *Conflict.* If a BIN's records name several different taxa, the BIN is
   attached at the last common ancestor of those names rather than being
   duplicated under each. 55,736 tips (4.9%) were placed this way, and they are
   marked `lifted=yes`.

Where the tips ended up:

| attachment rank | tips | share |
|---|---|---|
| family | 555,722 | 48.8% |
| species | 261,495 | 23.0% |
| genus | 151,825 | 13.3% |
| subfamily | 111,119 | 9.8% |
| order | 40,251 | 3.5% |
| class | 7,519 | 0.7% |
| tribe | 5,407 | 0.5% |
| subspecies | 4,585 | 0.4% |
| phylum (the root) | 983 | 0.1% |

Nearly half the tips sit directly under a family. That is a property of BOLD's
identification depth, not of the processing: only 4,812 of those reached family
by lifting, the rest never had a genus recorded.

One consequence worth knowing: 89,928 taxa (26.2% of those found in the dump,
overwhelmingly species) hold no terminal after placement and therefore do not
appear in the tree at all. Their only BIN was lifted past them. None of those
names are lost, they are in the `taxa` annotation of the tip that displaced them
and in the sidecar TSV, but you will not find them as nodes.

## Annotation fields

| field | meaning |
|---|---|
| `rank` | rank of the terminal, always `BIN` in this file |
| `records` | total BOLD records behind this BIN |
| `n_lineages` | how many distinct parent taxa its records named |
| `taxa` | those parent taxa, most-supported first |
| `counts` | record counts, in the same order as `taxa` |
| `placed_at` | the node this tip actually hangs from |
| `lifted` | present and `yes` only when placement was a compromise |
| `suspect` | present and `yes` when the lift reached family rank or above |

A value holding several items is written `{a,b,c}` and comes back as a list. A
single item is written bare and comes back as a string, because DendroPy
mishandles one-element brace lists. Code accordingly:

```python
taxa = ann["taxa"]
taxa = [taxa] if isinstance(taxa, str) else taxa
```

8,671 tips are `suspect`. Some are contamination, such as the BIN spanning 35
lineages that ended up at the root. Others are real: a BIN spanning 69 lineages
in Aphididae reflects COI failing to resolve aphid species, not a data error.
Treat the flag as a queue to inspect, not a delete list.

## Checking the file

`check_newick.py` streams the tree without building it, which takes seconds and
a few MB where a real parser needs minutes and gigabytes:

```
gunzip -c outfile.tre.gz > outfile.tre
python3 check_newick.py outfile.tre
```

Expect `tips 1138906`, `internals 253372`, `annotations 1138906`, and
`OK: balanced and terminated`.

## Parsing it

**DendroPy** gives structured annotations, which is what you want if you are
going to compute on them:

```python
import dendropy

tree = dendropy.Tree.get(path="outfile.tre", schema="newick",
                         extract_comment_metadata=True,
                         preserve_underscores=True)
for tip in tree.leaf_node_iter():
    ann = {a.name: a.value for a in tip.annotations}
    print(tip.taxon.label, ann["placed_at"], ann["records"])
```

`preserve_underscores=True` matters; without it underscores in labels become
spaces. Budget roughly 5 GB and a couple of minutes for the full file,
extrapolating from 1 GB and 31 s for a 250k-tip tree.

**Biopython** is much lighter but does not interpret the annotation, handing you
the raw comment string in `clade.comment` for you to split yourself:

```python
from Bio import Phylo

tree = Phylo.read("outfile.tre", "newick")
for tip in tree.get_terminals():
    fields = dict(part.split("=", 1)
                  for part in tip.comment.lstrip("&").split(","))
```

That naive split breaks on `{a,b}` list values, so use it only for scalar fields
or fall back to DendroPy. Budget roughly 1.5 GB and under a minute, from 319 MB
and 9 s at 250k tips.

**R** is untested here. `ape::read.tree` is fussy about bracketed comments and
will likely drop or choke on the annotations; if you need them in R, converting
to NEXUS with DendroPy first and reading with `treeio` is the safer route.

**Anything else**: the sidecar TSV carries the same per-tip information in a
plain table, with the unmangled names, and is far easier to join against than
parsing comments.

## Viewing it

Do not open the whole thing in FigTree. 1.1 million tips will exhaust any
interactive viewer, and half of them are in a single family-level polytomy that
no layout algorithm will render usefully.

Look at a clade instead. The cheapest way is to regenerate one from the dump,
which takes about five minutes and gives you a file of a sane size:

```
python3 bcdm2tree.py -i BOLD_Public.tar.gz -t family:Nymphalidae -l BIN \
    -o nymphalidae.tre -s nymphalidae.tsv
```

Any `rank:name` works as the root, so `-t genus:Vanessa` or `-t order:Diptera`
are equally valid. The resulting file opens fine in FigTree, Dendroscope,
Mesquite or iTOL, and FigTree will show the annotations as selectable node
attributes.

## Reproducing

Both scripts are in this repository. The tree took 5 minutes 11 seconds to build
from a 33 GB TSV inside a tar.gz, reading the archive as a stream, so it does not
need to be unpacked first. Peak memory is a few GB; this is a workstation job
rather than a laptop one.
