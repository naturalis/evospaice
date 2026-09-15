"""Create an Omni-DNA FAISS bundle from a FASTA blob."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from collections.abc import Iterator
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

import faiss
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import torch
from fasta import FastaRecord, iter_fasta_records
from transformers import AutoModelForCausalLM, AutoTokenizer

LOGGER = logging.getLogger("omni_dna_embedding")
METADATA_ROW_GROUP_SIZE = 16_384
METADATA_COLUMNS = (
    "faiss_id",
    "source_record_number",
    "record_id",
    "header",
    "sequence",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "species",
    "source_blob_url",
)


def _batches(records: Iterator[FastaRecord], batch_size: int) -> Iterator[list[FastaRecord]]:
    batch: list[FastaRecord] = []
    for record in records:
        batch.append(record)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _pool_embeddings(model, tokenizer, sequences: list[str], max_length: int) -> np.ndarray:
    encoded = tokenizer(
        sequences,
        add_special_tokens=True,
        max_length=max_length,
        padding=True,
        return_tensors="pt",
        truncation=True,
    )
    encoded = {name: tensor.to(model.device) for name, tensor in encoded.items()}
    token_mask = encoded["attention_mask"].bool()

    autocast = (
        torch.autocast(device_type="cuda", dtype=torch.bfloat16)
        if model.device.type == "cuda"
        else nullcontext()
    )
    with torch.inference_mode(), autocast:
        outputs = model(**encoded, output_hidden_states=True, use_cache=False, return_dict=True)
        hidden = outputs.hidden_states[-1]
        weights = token_mask.unsqueeze(-1)
        pooled = (hidden * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1)
        pooled = torch.nn.functional.normalize(pooled.float(), p=2, dim=1)
    return pooled.cpu().numpy().astype(np.float32, copy=False)


def _metadata_table(records: list[FastaRecord], source_blob_url: str) -> pa.Table:
    rows = []
    for record in records:
        rows.append(
            {
                "faiss_id": record.ordinal,
                "source_record_number": record.ordinal,
                "record_id": record.record_id,
                "header": record.header,
                "sequence": record.sequence,
                **record.taxonomy,
                "source_blob_url": source_blob_url,
            }
        )
    return pa.Table.from_pylist(rows).select(METADATA_COLUMNS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_chunks(path: Path, chunk_size: int = 4 * 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            yield chunk


def _resolve_source_path(path: Path) -> Path:
    if path.is_file():
        return path
    files = [candidate for candidate in path.rglob("*") if candidate.is_file()]
    if len(files) != 1:
        raise ValueError(f"Expected one downloaded FASTA file under {path}, found {len(files)}")
    return files[0]


def embed_fasta(
    source_fasta: Path,
    source_blob_url: str,
    source_etag: str,
    output_dir: Path,
    model_id: str,
    batch_size: int,
    max_length: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_fasta = _resolve_source_path(source_fasta)

    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device).eval()

    index = None
    metadata_writer = None
    metadata_buffer: list[FastaRecord] = []
    metadata_path = output_dir / "records.parquet"
    record_count = 0

    try:
        records = iter_fasta_records(_file_chunks(source_fasta))
        for batch in _batches(records, batch_size):
            vectors = _pool_embeddings(
                model,
                tokenizer,
                [record.sequence for record in batch],
                max_length,
            )
            if index is None:
                index = faiss.IndexIDMap2(faiss.IndexFlatIP(vectors.shape[1]))
            ids = np.asarray([record.ordinal for record in batch], dtype=np.int64)
            index.add_with_ids(vectors, ids)

            metadata_buffer.extend(batch)
            if len(metadata_buffer) >= METADATA_ROW_GROUP_SIZE:
                table = _metadata_table(metadata_buffer, source_blob_url)
                if metadata_writer is None:
                    metadata_writer = pq.ParquetWriter(
                        metadata_path,
                        table.schema,
                        compression="zstd",
                    )
                metadata_writer.write_table(table)
                metadata_buffer.clear()
            record_count += len(batch)
            if record_count % 10000 < len(batch):
                LOGGER.info("Embedded %d FASTA records", record_count)
    finally:
        if metadata_buffer:
            table = _metadata_table(metadata_buffer, source_blob_url)
            if metadata_writer is None:
                metadata_writer = pq.ParquetWriter(
                    metadata_path,
                    table.schema,
                    compression="zstd",
                )
            metadata_writer.write_table(table)
        if metadata_writer is not None:
            metadata_writer.close()

    if index is None:
        raise ValueError("Source FASTA contains no records")

    index_path = output_dir / "index.faiss"
    temporary_index_path = output_dir / ".index.faiss.tmp"
    faiss.write_index(index, str(temporary_index_path))
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source": {
            "blob_url": source_blob_url,
            "etag": source_etag,
            "size_bytes": source_fasta.stat().st_size,
        },
        "model": {
            "id": model_id,
            "revision": getattr(model.config, "_commit_hash", None),
            "max_length": max_length,
            "pooling": "attention_masked_mean_final_hidden_state",
        },
        "index": {
            "type": "IndexIDMap2(IndexFlatIP)",
            "metric": "cosine_similarity",
            "normalized": True,
            "dimension": index.d,
            "record_count": record_count,
            "file": index_path.name,
            "sha256": _sha256(temporary_index_path),
        },
        "metadata": {
            "format": "parquet",
            "file": metadata_path.name,
            "sha256": _sha256(metadata_path),
            "id_column": "faiss_id",
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(temporary_index_path, index_path)
    LOGGER.info("Wrote %d embeddings to %s", record_count, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-fasta", required=True, type=Path)
    parser.add_argument("--source-blob-url", required=True)
    parser.add_argument("--source-etag", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--model-id", default="zehui127/Omni-DNA-20M")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--max-length", type=int, default=1024)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    embed_fasta(**vars(args))


if __name__ == "__main__":
    main()