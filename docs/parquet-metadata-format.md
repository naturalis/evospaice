# Parquet metadata format

The embedding pipeline uses Parquet as the metadata sidecar for each FAISS index.
It stores the source FASTA record and taxonomy associated with every vector.

## Files

The global embedding bundle contains:

```text
embedding-results/<source>/<source-etag>/
  index.faiss
  records.parquet
  manifest.json
```

The species splitter writes metadata subsets using the same columns:

```text
species-results/<source>/<source-etag>/
  <species-key>.faiss
  <species-key>.parquet
  <species-key>.json
```

Each Parquet file is paired with a FAISS index and JSON manifest. The JSON
manifest records the filenames, record count, vector dimension, model details,
and SHA-256 checksums.

## Schema

| Column | Arrow/Parquet type | Required by contract | Description |
|---|---|---:|---|
| `faiss_id` | `int64` | Yes | Stable integer stored in the paired FAISS `IndexIDMap2`. |
| `source_record_number` | `int64` | Yes | Zero-based ordinal of the record in the filtered source FASTA. |
| `record_id` | UTF-8 string | Yes | BOLD process ID, or the first token of a non-BOLD FASTA header. |
| `header` | UTF-8 string | Yes | Complete FASTA header without the leading `>` character. |
| `sequence` | UTF-8 string | Yes | Uppercase sequence with FASTA line breaks removed. |
| `kingdom` | UTF-8 string | No | Parsed kingdom name. Missing values are null. |
| `phylum` | UTF-8 string | No | Parsed phylum name. Missing values are null. |
| `class` | UTF-8 string | No | Parsed class name. Missing values are null. |
| `order` | UTF-8 string | No | Parsed order name. Missing values are null. |
| `family` | UTF-8 string | No | Parsed family name. Missing values are null. |
| `genus` | UTF-8 string | No | Parsed genus name. Missing values are null. |
| `species` | UTF-8 string | No | Parsed species name. Missing values are null. |
| `source_blob_url` | UTF-8 string | Yes | URL of the filtered FASTA used to generate the embedding. |

Parquet marks every physical column as optional, but consumers should enforce the
contract above. This keeps missing taxonomy ranks nullable while preserving a
one-to-one mapping between required metadata rows and FAISS IDs.

## FAISS mapping

`faiss_id` is the join key between Parquet and FAISS. The global index uses:

```text
IndexIDMap2(IndexFlatIP)
```

Vectors are 256-dimensional `float32`, L2-normalized Omni-DNA 20M embeddings.
Inner product therefore represents cosine similarity.

For the global production bundle:

- `faiss_id` is unique and contiguous from `0` through `6,979,066`.
- `source_record_number` currently equals `faiss_id`.
- There are `6,979,067` Parquet rows and FAISS vectors.

Species subsets retain the original global IDs. Do not assume that row position
inside a species Parquet file equals its FAISS ID; always use `faiss_id`.

## Taxonomy encoding

BOLD taxonomy is parsed from rank-prefixed header fields:

| Prefix | Column |
|---|---|
| `k__` | `kingdom` |
| `p__` | `phylum` |
| `c__` | `class` |
| `o__` | `order` |
| `f__` | `family` |
| `g__` | `genus` |
| `s__` | `species` |

The literal value `None` is stored as null. The species splitter also treats
blank, `unknown`, `unidentified`, `unclassified`, `na`, and `n/a` labels as
unknown and writes them to `unknown.parquet` with matching `unknown.faiss` and
`unknown.json` files.

### Current production caveat

In the production file at
`embedding-results/insecta/0x8df1258ad040f84/records.parquet`, `kingdom` contains
no values and is physically encoded as Parquet `INT32` with logical `NullType`.
Consumers should treat it as a nullable string contractually and cast it when
combining this artifact with future files. Other populated taxonomy fields are
UTF-8 strings.

## Encoding

The global production metadata uses:

- ZSTD compression for all columns.
- 426 row groups.
- 16,384 rows per full row group.
- 15,867 rows in the final row group.
- A production file size of 346,222,372 bytes.

Per-species files also use ZSTD compression. Their row-group size depends on the
number of records for that species, up to 65,536 rows per written batch.

## Example queries

Count records by species, treating null species as unknown:

```sql
SELECT
    coalesce(species, 'Unknown') AS species,
    count(*) AS record_count
FROM read_parquet('records.parquet')
GROUP BY coalesce(species, 'Unknown')
ORDER BY record_count DESC, species;
```

Look up metadata for FAISS IDs returned by a nearest-neighbor search:

```sql
SELECT *
FROM read_parquet('records.parquet')
WHERE faiss_id IN (42, 1234, 5678);
```

Verify the global ID invariant:

```sql
SELECT
    count(*) AS rows,
    count(DISTINCT faiss_id) AS unique_ids,
    min(faiss_id) AS min_id,
    max(faiss_id) AS max_id
FROM read_parquet('records.parquet');
```
