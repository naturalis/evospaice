"""Encode DNA sequences from FASTA files using pluggable model families.

Supported families (via --family):
    omnidna     OmniDNA 20M–1B  (default)
    mamba       BarcodeMamba+ 384D  (placeholder)
    dnabert-s   DNABERT-S 768D  (placeholder)

Usage (local):
    python -m encoder --fasta data/referencedata/BOLD/20260327/BOLD_10k_sample.fasta

    # Explicit family selection
    python -m encoder --family omnidna --model zehui127/Omni-DNA-700M --fasta ...

    # With checkpointing (saves a shard every 50 000 sequences, resumes on restart)
    python -m encoder --fasta large.fasta --checkpoint-every 50000

Usage (AML, via Makefile):
    make aml pkg=encoder
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import re
import time
from pathlib import Path

import numpy as np

from evospaice.embeddings.encoder._fasta import parse_fasta
from evospaice.embeddings.encoder._logging import AMLLogger
from evospaice.embeddings.encoder._omnidna import DEFAULT_MODEL
from evospaice.embeddings.encoder._registry import REGISTRY, create_encoder

# Import adapters so they register themselves.
import evospaice.embeddings.encoder._omnidna  # noqa: F401
import evospaice.embeddings.encoder._mamba  # noqa: F401
import evospaice.embeddings.encoder._dnabert  # noqa: F401

logger = logging.getLogger(__name__)

OUTPUTS_DIR = Path(os.getenv("OUTPUTS_DIR", "./outputs"))

SHARD_PATTERN = re.compile(r"^(.+)\.shard_(\d+)\.npz$")


def _shard_dir(output_dir: Path, stem: str) -> Path:
    return output_dir / f".checkpoints_{stem}"


def _find_existing_shards(shard_directory: Path) -> list[Path]:
    if not shard_directory.exists():
        return []
    shards = sorted(
        shard_directory.glob("shard_*.npz"),
        key=lambda p: int(p.stem.split("_")[1]),
    )
    return shards


def _count_checkpointed_sequences(shards: list[Path]) -> int:
    total = 0
    for s in shards:
        data = np.load(s, allow_pickle=True)
        total += len(data["ids"])
        data.close()
    return total


def _merge_shards(shards: list[Path], output_path: Path) -> tuple[np.ndarray, np.ndarray]:
    all_ids: list[np.ndarray] = []
    all_emb: list[np.ndarray] = []
    meta_keys = None
    all_meta: dict[str, list[np.ndarray]] = {}
    
    for s in shards:
        data = np.load(s, allow_pickle=True)
        all_ids.append(data["ids"])
        all_emb.append(data["embeddings"])
        
        if meta_keys is None:
            meta_keys = [k for k in data.keys() if k not in ("ids", "embeddings")]
            for k in meta_keys:
                all_meta[k] = []
        for k in meta_keys:
            all_meta[k].append(data[k])
            
        data.close()
        
    ids = np.concatenate(all_ids)
    embeddings = np.vstack(all_emb)
    
    save_kwargs = {"ids": ids, "embeddings": embeddings}
    for k in (meta_keys or []):
        save_kwargs[k] = np.concatenate(all_meta[k])
        
    np.savez(output_path, **save_kwargs)
    return ids, embeddings


def encode_fasta(
    fasta_path: Path,
    output_dir: Path,
    encoder,
    batch_size: int,
    checkpoint_every: int = 0,
    model_prefix: str = "",
) -> tuple[np.ndarray, np.ndarray] | None:
    """Encode a single FASTA file. Returns (ids_array, embeddings) or None.

    When *checkpoint_every* > 0, intermediate results are saved as shards
    under ``output_dir/.checkpoints_<stem>/``.  On restart, already-encoded
    sequences are skipped automatically.
    """
    ids, seqs, metadata = parse_fasta(fasta_path)
    logger.info("Loaded %d sequences from %s", len(ids), fasta_path)

    if not seqs:
        logger.warning("No sequences found in %s, skipping", fasta_path)
        return None

    seq_lengths = [len(s) for s in seqs]
    logger.info(
        "Sequence lengths — min: %d, max: %d, mean: %.0f",
        min(seq_lengths),
        max(seq_lengths),
        sum(seq_lengths) / len(seq_lengths),
    )

    filename = f"{model_prefix}_{fasta_path.stem}" if model_prefix else fasta_path.stem
    stem = filename
    final_path = output_dir / f"{stem}.npz"

    # --- resume from checkpoints ---
    skip = 0
    shard_idx = 0
    ckpt_dir = _shard_dir(output_dir, stem)

    if checkpoint_every > 0:
        existing_shards = _find_existing_shards(ckpt_dir)
        if existing_shards:
            skip = _count_checkpointed_sequences(existing_shards)
            shard_idx = len(existing_shards)
            logger.info(
                "Resuming: found %d shards with %d sequences, skipping to index %d",
                shard_idx, skip, skip,
            )
            if skip >= len(seqs):
                logger.info("All sequences already encoded, merging shards")
                ids_array, embeddings = _merge_shards(existing_shards, final_path)
                logger.info("Saved %s", final_path)
                return ids_array, embeddings
        ckpt_dir.mkdir(parents=True, exist_ok=True)

    remaining_ids = ids[skip:]
    remaining_seqs = seqs[skip:]
    remaining_metadata = {k: v[skip:] for k, v in metadata.items()}

    t0 = time.perf_counter()

    if checkpoint_every > 0:
        all_shard_paths: list[Path] = _find_existing_shards(ckpt_dir)
        for chunk_start in range(0, len(remaining_seqs), checkpoint_every):
            chunk_end = min(chunk_start + checkpoint_every, len(remaining_seqs))
            chunk_seqs = remaining_seqs[chunk_start:chunk_end]
            chunk_ids = remaining_ids[chunk_start:chunk_end]
            chunk_meta = {k: v[chunk_start:chunk_end] for k, v in remaining_metadata.items()}

            chunk_embeddings = encoder.encode(chunk_seqs, batch_size=batch_size)

            shard_path = ckpt_dir / f"shard_{shard_idx:05d}.npz"
            save_kwargs = {"ids": np.array(chunk_ids), "embeddings": chunk_embeddings}
            for k, v in chunk_meta.items():
                save_kwargs[k] = np.array(v)
            np.savez(shard_path, **save_kwargs)
            all_shard_paths.append(shard_path)
            shard_idx += 1

            done_total = skip + chunk_end
            logger.info(
                "Checkpoint shard %d saved: %d/%d sequences (%.1f%%)",
                shard_idx, done_total, len(seqs), 100.0 * done_total / len(seqs),
            )

        ids_array, embeddings = _merge_shards(all_shard_paths, final_path)
    else:
        embeddings = encoder.encode(remaining_seqs, batch_size=batch_size)
        ids_array = np.array(ids)
        save_kwargs = {"ids": ids_array, "embeddings": embeddings}
        for k, v in metadata.items():
            save_kwargs[k] = np.array(v)
        np.savez(final_path, **save_kwargs)

    elapsed = time.perf_counter() - t0
    throughput = len(remaining_seqs) / elapsed if elapsed > 0 else 0
    logger.info(
        "Embedding matrix: %s (%.1f sec, %.2f seq/s)",
        embeddings.shape,
        elapsed,
        throughput,
    )
    logger.info("Saved %s", final_path)
    return ids_array, embeddings


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main() -> None:
    import torch

    families = sorted(REGISTRY)
    parser = argparse.ArgumentParser(description="Encode FASTA sequences with a DNA foundation model")
    parser.add_argument(
        "--family",
        choices=families,
        default=None,
        help=f"Model family ({', '.join(families)}). Default: inferred from --model or omnidna.",
    )
    parser.add_argument("--fasta", type=Path, required=True, help="Path to a FASTA file")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="HuggingFace model name")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--checkpoint-every",
        type=int,
        default=0,
        help="Save a checkpoint shard every N sequences (0 = disabled).",
    )
    parser.add_argument(
        "--device",
        default="cuda" if torch.cuda.is_available() else "cpu",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    # Infer family from --model when --family is omitted (backward compat).
    if args.family is None:
        if "Omni-DNA" in args.model:
            args.family = "omnidna"
        else:
            args.family = "omnidna"

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    output_dir = OUTPUTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    aml_logger = AMLLogger()
    aml_logger.set_tags({"family": args.family, "model": args.model, "fasta": args.fasta.name})

    logger.info(
        "encoder | family=%s | device=%s | model=%s | outputs=%s",
        args.family, args.device, args.model, output_dir,
    )

    # Create encoder via registry
    logger.info("Loading model: %s (family=%s)", args.model, args.family)
    t0 = time.perf_counter()
    encoder = create_encoder(args.family, model_name=args.model, device=args.device)
    load_time = time.perf_counter() - t0
    logger.info("Model loaded in %.1f sec", load_time)

    # Derive model prefix for output filename (e.g. "zehui127/Omni-DNA-60M" -> "omni-dna-60m")
    model_prefix = args.model.split("/")[-1].lower()

    # Encode
    result = encode_fasta(
        args.fasta, output_dir, encoder, args.batch_size,
        checkpoint_every=args.checkpoint_every,
        model_prefix=model_prefix,
    )
    if result is None:
        logger.error("No sequences encoded")
        raise SystemExit(1)

    ids_array, embeddings = result
    encode_time = time.perf_counter() - t0 - load_time
    aml_logger.log_metrics({
        "seq_count": len(ids_array),
        "embedding_dim": int(embeddings.shape[1]),
        "throughput_seq_s": len(ids_array) / encode_time if encode_time > 0 else 0,
        "model_load_s": load_time,
    })
    logger.info("Done")


if __name__ == "__main__":
    main()
