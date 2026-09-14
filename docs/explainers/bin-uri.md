# What is a BIN URI?

`bin_uri` is the identifier for a **BOLD Barcode Index Number (BIN)**.

BOLD is a database of DNA barcode records. It groups barcode sequences that
are very similar into clusters called BINs. A BIN often acts as a practical
species proxy when the formal species name is missing or uncertain.

For example:

```text
record_id: GBMIN12345-24
bin_uri:   BOLD:AAA1234
```

The identifiers describe different things:

- `record_id` identifies one specimen or DNA sequence record.
- `bin_uri` identifies the larger barcode cluster containing that record.
- `leaf_id` identifies a tip in the generated tree. In this project it is
  normally set to the `bin_uri`.

Many specimen records can belong to the same BIN:

```text
BIN: BOLD:AAA1234
|-- specimen record 1
|-- specimen record 2
`-- specimen record 3
```

## Why the tree needs it

This project aims to create approximately **one tree leaf per BIN**, rather
than one leaf per specimen.

Without BIN grouping, a frequently sampled organism could produce hundreds of
nearly identical tree leaves. That would make the organism appear more
important simply because more specimens were collected. Selecting one
representative record and embedding per BIN reduces this sampling bias.

The `bin_uri` is used to:

1. **Group related records.** Records assigned to the same BIN belong to the
   same barcode cluster.
2. **Prevent duplicate tree tips.** The pipeline can select one representative
   embedding for each BIN.
3. **Provide a stable tree label.** Taxonomic names may be missing, misspelled,
   or revised, while the BIN remains a useful reference identifier.
4. **Preserve provenance.** A tree tip can be traced to its BOLD BIN and then
   to the specimen record selected to represent it.
5. **Connect downstream results.** A result referring to `BOLD:AAA1234` can be
   matched directly to the corresponding tree leaf.

The tree model stores all three identifiers:

```python
@dataclass(frozen=True)
class TreeRecord:
    leaf_id: str
    record_id: str
    bin_uri: str
```

For a typical input record:

```text
one specimen record -> one selected embedding -> one BIN -> one tree leaf
```

## Production record-to-BIN map

The production embedding export contains 6,979,067 records. Its
`records.parquet` file contains `record_id` and taxonomy, but it does not
contain `bin_uri`. The tree preparation stage therefore needs a separate
`record-bin-map.parquet` file.

This file has one row per embedded record:

| Column | Meaning | Production requirement |
| --- | --- | --- |
| `record_id` | Identifier also present in `records.parquet` | String, unique, non-null, and present exactly once |
| `bin_uri` | Official BOLD BIN assigned to the record | String, non-null, and non-empty |

For example:

```text
record_id       bin_uri
GBMIN12345-24   BOLD:AAA1234
GBMIN12346-24   BOLD:AAA1234
GBMIN55555-24   BOLD:AAB9876
```

It is normal for `bin_uri` to occur more than once because several specimen
records can belong to the same BIN. Only `record_id` must be unique.

### Where the assignments must come from

Obtain an authoritative BOLD export or API result containing both the stable
record identifier and the official BIN assignment. The identifier must have
the same meaning and format as `records.parquet.record_id`.

Do not generate official-looking `BOLD:...` values from `index.faiss` or from
embedding clusters. Embeddings can produce useful project-defined, BIN-like
groups, but only BOLD supplies official BOLD BIN assignments. An inferred
cluster must use a project-controlled identifier such as
`urn:evospaice:binlike:...` and must be marked as inferred.

### How to construct the file

1. Freeze the embedding manifest and authoritative BOLD source versions.
2. Read all `record_id` values from the production `records.parquet`.
3. Join them exactly to the BOLD assignments. Do not use fuzzy name matching.
4. Collapse duplicate source rows only when they give the same BIN assignment.
5. Quarantine any record associated with two different BINs.
6. Reject null, empty, and whitespace-only identifiers.
7. Write only `record_id` and `bin_uri` to a compressed Parquet file.

A conceptual DuckDB query for the final join is:

```sql
COPY (
    SELECT
        CAST(records.record_id AS VARCHAR) AS record_id,
        TRIM(CAST(bold.bin_uri AS VARCHAR)) AS bin_uri
    FROM read_parquet('records.parquet') AS records
    INNER JOIN read_parquet('bold-bin-assignments.parquet') AS bold
        ON records.record_id = bold.record_id
) TO 'record-bin-map.parquet'
  (FORMAT PARQUET, COMPRESSION ZSTD);
```

An inner join can silently discard unmatched records, so coverage and conflict
queries must run before the result is accepted.

### Acceptance checks

The production map is ready only when all of these checks pass:

```text
row count                         = 6,979,067
distinct record_id count          = 6,979,067
null record_id count              = 0
null or blank bin_uri count       = 0
records without a mapping         = 0
mappings without an embedded row  = 0
record IDs with conflicting BINs  = 0
```

Retain an audit record containing:

- the SHA-256 checksum of `record-bin-map.parquet`;
- the BOLD export version and retrieval date;
- the source and embedding-manifest checksums;
- the exact join-key definition; and
- counts of duplicate source rows, conflicts, unmatched records, and
  exclusions.

The preparation stage validates column presence, uniqueness, non-null BINs,
row count, complete joins, and non-empty strings before opening the large
FAISS index. It then groups records by `bin_uri` and deterministically selects
the record with the lowest `faiss_id` as that BIN's tree representative.

This deterministic choice is reproducible, but it is not a biological quality
ranking. The scientific team should confirm that it is acceptable or define a
quality-based representative-selection rule before production publication.

If any embedded record lacks an official BIN, the current strict full-scale
run cannot proceed. The defensible choices are to obtain the missing BOLD
assignment or rebuild the embedding export from BIN-assigned records. A BOLD
identifier must not be fabricated merely to pass the input check.

## Important limitation

A BIN is an algorithmically generated DNA barcode cluster. It is useful as an
operational unit, but it is not definitive proof that all records in the BIN
belong to one biological species. Scientists may later split a BIN, combine
BINs, or assign a different taxonomic interpretation as more evidence becomes
available.

## Related production gate: trust policy

The BIN map decides which records become tree leaves. A separate
`trust-policy.json` decides where embedding distances are reliable enough to
change tree topology or assign branch lengths.

The operational file supports this structure:

```json
{
  "version": "insecta-omnidna20m-production-v1",
  "resolve_ranks": ["genus", "species"],
  "scale_ranks": ["genus", "species"]
}
```

`resolve_ranks` lists taxonomy nodes where embedding distances may turn an
unresolved group into a Neighbor-Joining topology. `scale_ranks` lists nodes
where those distances may be used to fit branch lengths. These are independent
decisions because topology can be reliable even when distance magnitude is
not, or the reverse.

Valid rank names are:

```text
kingdom, phylum, class, order, family, subfamily,
tribe, genus, species, subspecies
```

The wildcard `*` permits an operation at every rank. An empty list disables it
everywhere. A production policy should use `*` only if every rank passed
validation. The repository's mock policy is demonstration data, not production
scientific evidence.

### How to validate the policy

1. Select a trusted insect COI reference tree and record its marker, licence,
   version, and checksum.
2. Map BOLD records or BINs to reference tips with explicit counts for exact,
   ambiguous, unmatched, and excluded records.
3. Define sample sizes, metrics, uncertainty methods, and pass thresholds
   before evaluating results.
4. Separate calibration data from held-out clades to prevent data leakage.
5. Evaluate each taxonomic rank independently and compare embeddings with a
   k-mer baseline.
6. Bootstrap over clades to calculate confidence intervals.
7. Approve only ranks whose held-out results and confidence bounds pass all
   predefined gates.

Topology evidence should include quartet or triplet ordering, clade recovery,
reference-tree agreement, and performance relative to the baseline.
Branch-length evidence should include correlation with reference patristic
distances, fit error, additivity error, behavior by depth, and tests for
flattened or near-zero terminal distances.

Store the complete evidence in a versioned `validation-report.json`, including
the model revision, input checksums, reference identity, crosswalk counts,
sample sizes, metrics, confidence intervals, approved and rejected ranks,
fallback decisions, validation code version, reviewer, date, and limitations.
The policy `version` must identify that immutable evidence package.

The software checks that the policy is valid JSON with string rank lists, but
it cannot determine whether the policy is scientifically justified. Scientific
review and held-out evidence are therefore part of the production run gate.
