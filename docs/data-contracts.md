# Pipeline data contracts

## Class-filter trigger

Container: `pipeline-triggers`

```json
{
  "source_blob_url": "https://<account>.blob.core.windows.net/<container>/<file>.fasta",
  "target_class": "Insecta"
}
```

Both fields are required. `target_class` must start with a letter and contain
only letters, numbers, underscores, or hyphens.

Output convention:

```text
filtered-sequences/<target_class lowercase>.fasta
```

## FASTA contract

- Headers begin with `>` and are UTF-8.
- Sequences are ASCII nucleotide strings.
- Class metadata supports `class=<value>`, `class:<value>`, and BOLD `c__<value>`.
- Fields may be separated by whitespace, `|`, or `;`.
- Records without class metadata are excluded by the class filter.

BOLD taxonomy prefixes:

| Prefix | Rank |
|---|---|
| `k__` | kingdom |
| `p__` | phylum |
| `c__` | class |
| `o__` | order |
| `f__` | family |
| `g__` | genus |
| `s__` | species |

## Event Grid envelope

Functions consume Event Grid BlobCreated events from Service Bus. Required event
fields are:

```json
{
  "eventType": "Microsoft.Storage.BlobCreated",
  "data": {
    "url": "https://<account>.blob.core.windows.net/<container>/<blob>",
    "eTag": "<blob-etag>"
  }
}
```

Functions validate the expected storage host, container, and filename suffix.

## Global embedding bundle

```text
embedding-results/<source-name>/<source-etag>/
  index.faiss
  records.parquet
  manifest.json
```

`index.faiss` is an `IndexIDMap2(IndexFlatIP)` containing normalized float32
vectors. `records.parquet.faiss_id` maps vectors to source FASTA records.
`manifest.json` contains source identity, model identity, dimensions, counts,
filenames, and SHA-256 checksums.

See [parquet-metadata-format.md](parquet-metadata-format.md) for the complete
Parquet schema.

## Species key

Known species use:

```text
<lowercase sanitized species>-<10-character SHA-256 prefix>
```

Example:

```text
danaus-plexippus-b0b40e6e0c
```

The hash prevents collisions between labels that sanitize to the same slug.
Species identity is case-insensitive.

These values map to `unknown`:

- null or blank
- `None`
- `unknown`
- `unidentified`
- `unclassified`
- `na` or `n/a`

## Per-species bundle

All species files for one source version share one folder:

```text
species-results/<source-name>/<source-etag>/
  <species-key>.faiss
  <species-key>.parquet
  <species-key>.json
```

Eight workers operate concurrently, but stable hashing assigns each species to
exactly one worker. Species filenames are globally unique, so no shard directory
is required.

The species FAISS index retains global `faiss_id` values. The Parquet subset uses
the global metadata schema. The JSON file records species identity, source
manifest, counts, dimensions, and checksums.

## Versioning

- Source FASTA ETag versions the global embedding bundle.
- Global `index.faiss` ETag versions deterministic splitter job names.
- Schema versions appear in JSON manifests.
- Consumers must not mix files from different source ETag folders.
