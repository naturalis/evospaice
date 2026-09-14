# Taxonomy and phylogenetics of nudibranchs. 

Several beautifull seaslugs (from the Flabellina family)

| <img src="https://cdn.blauwtipje.nl/database-images/species-34.jpg" width="150"> | <img src="https://cdn.blauwtipje.nl/database-images/species-36.jpg" width="150"> | <img src="https://cdn.blauwtipje.nl/database-images/animal-35.png" width="150"> | <img src="https://images.marinespecies.org/thumbs/117184_flabellina-trophina.jpg?w=700" height="150"> | <img src="https://images.marinespecies.org/thumbs/117185_orienthella-trilineata.jpg?w=700" height="150"> | <img src="https://www.dykking.no/images/nyhetsbilder/2026/26.06122.01a.jpg" height="150"> | <img src="https://damsl.org/wp-content/uploads/2014/11/1967.jpg" height="150"> |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Flabellina gracilis | Flabellina lineata | Flabellina pedata | Flabellina trophina | Flabbelina trilineata | Flabbelina albomaculata | Flabbelina exoptata |

In the the taxonomic tree (note: outdated since 2017) they were positioned like this based on morphology

```mermaid
flowchart TD
    F[Family: Flabellinidae] --> G1[Genus: Flabellina]
    G1 --> S1[Species: Flabellina lineata]
    G1 --> S4[Species: Flabellina gracilis]
    G1 --> S6[Species: Flabellina pedata]
    G1 --> S2[Flabellina trophina]
    G1 --> S3[Flabellina trilineata]
    G1 --> S5[Flabellina albomaculata]
    G1 --> S7[Flabellina exoptata]
```
__[source, January 2018](https://www.sciencedirect.com/science/article/abs/pii/S1055790317302191?via%3Dihub)__

However when they created a phylogenetic tree based on the moleculair DNA divergence it looked like this:
```mermaid
flowchart TD
    S1[Flabellina lineata]
    S2[Flabellina trophina]
    S3[Flabellina trilineata]
    S4[Flabellina gracilis]
    S5[Flabellina albomaculata]
    S6[Flabellina pedata]
    S7[Flabellina exoptata]
    N1[0.67] --> S1
    N1 --> S2
    N2[0.92] --> N1
    N2 --> S3
    N3[1] --> N2
    N3 --> S4
    N5[1] --> S5
    N5 --> S6
    N6[0.79] --> N5
    N6 --> S7
    N7[1] --> N6
    N7 --> N3
```

__[source, January 2018](https://www.sciencedirect.com/science/article/abs/pii/S1055790317302191?via%3Dihub)__

We can read that some species within this genus where more closely related than others. Note, from the taxonomic tree this is somehting you cannot read. So the writers of this article (and a few authors of more articles later) moved the species into new genera which became this taxonomic tree. Note: the second part (epithet) of the species name has not changed.

```mermaid
flowchart TD
    F[Family: Flabellinidae] --> G1[Genus: Flabellina]
    F --> G2["Genus: Coryphella"]
    F --> G3["Genus: Edmundsella"]
    F --> G4["Genus: Coryphellina"]

    G1 --> S1[Flabellina lineata]
    G2 --> S4[Coryphella gracilis]
    G3 --> S6[Edmundsella pedata]
    G2 --> S2[Coryphella trophina]
    G2 --> S3[Coryphella trilineata]
    G3 --> S5[Edmundsella albomaculata]
    G4 --> S7[Coryphellina exoptata]
```

__[source](https://www.marinespecies.org/aphia.php?p=taxdetails&id=138019)__



