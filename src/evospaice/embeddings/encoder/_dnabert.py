"""DNABERT-S encoder adapter (768D, mean-pooled hidden states).

Uses the pretrained DNABERT-S model from HuggingFace (zhihan1996/DNABERT-S).
Requires CUDA at runtime.

The remote model code ships a Triton flash-attention kernel that is
incompatible with newer Triton versions (removed ``trans_b`` kwarg).
We shim flash_attn with PyTorch SDPA and nullify the Triton path so the
model falls back to the pure-PyTorch attention implementation.

Requirements:
    torch, transformers (already in base deps).
"""

from __future__ import annotations

import logging
import sys
import types
from typing import TYPE_CHECKING, Any

from evospaice.embeddings.encoder._registry import register

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "zhihan1996/DNABERT-S"
MAX_LENGTH = 512


def _install_flash_attention_shim() -> None:
    """Register a flash_attn shim backed by PyTorch scaled_dot_product_attention.

    Must be called BEFORE importing/loading the DNABERT-S model so that the
    remote bert_layers.py resolves the symbol to our shim instead of Triton.
    """
    if "flash_attn" in sys.modules:
        return

    import torch.nn.functional as F

    def _flash_attn_func(
        q: Any, k: Any, v: Any,
        dropout_p: float = 0.0,
        softmax_scale: float | None = None,
        causal: bool = False,
        **_: Any,
    ) -> Any:
        if softmax_scale is not None:
            q = q * softmax_scale
        return F.scaled_dot_product_attention(
            q, k, v, attn_mask=None,
            dropout_p=float(dropout_p) if dropout_p else 0.0,
            is_causal=bool(causal),
        )

    def _flash_attn_qkvpacked_func(
        qkv: Any,
        dropout_p: float = 0.0,
        softmax_scale: float | None = None,
        causal: bool = False,
        **kwargs: Any,
    ) -> Any:
        q, k, v = qkv.unbind(dim=2)
        return _flash_attn_func(q, k, v, dropout_p=dropout_p,
                                softmax_scale=softmax_scale, causal=causal, **kwargs)

    import importlib

    flash_attn_mod = types.ModuleType("flash_attn")
    flash_attn_interface_mod = types.ModuleType("flash_attn.flash_attn_interface")
    flash_attn_triton_mod = types.ModuleType("flash_attn_triton")

    for mod in (flash_attn_mod, flash_attn_interface_mod, flash_attn_triton_mod):
        mod.flash_attn_func = _flash_attn_func  # type: ignore[attr-defined]
        mod.flash_attn_qkvpacked_func = _flash_attn_qkvpacked_func  # type: ignore[attr-defined]

    # Set __spec__ so importlib.util.find_spec doesn't raise ValueError
    flash_attn_mod.__spec__ = importlib.machinery.ModuleSpec("flash_attn", None)
    flash_attn_mod.__version__ = "2.6.3"  # satisfy transformers version checks

    sys.modules["flash_attn"] = flash_attn_mod
    sys.modules["flash_attn.flash_attn_interface"] = flash_attn_interface_mod
    sys.modules["flash_attn_triton"] = flash_attn_triton_mod


@register("dnabert-s")
class DNABertSEncoder:
    """DNABERT-S encoder (768D, mean-pooled hidden states)."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "cuda") -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                "DNABERT-S uses Triton flash attention and requires CUDA, "
                "but no CUDA device is available."
            )

        _install_flash_attention_shim()

        self._device = torch.device(device)
        self._tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self._model = AutoModel.from_pretrained(model_name, trust_remote_code=True).to(self._device)
        self._model.eval()
        self._force_non_triton_attention_path()
        self._embedding_dim = 768

    def _force_non_triton_attention_path(self) -> None:
        """Nullify flash_attn_qkvpacked_func in bert_layers to force PyTorch path."""
        patched = 0
        for module in self._model.modules():
            mod = type(module).__module__ or ""
            if "bert_layers" not in mod:
                continue
            parent_mod = sys.modules.get(mod)
            if parent_mod is not None and hasattr(parent_mod, "flash_attn_qkvpacked_func"):
                parent_mod.flash_attn_qkvpacked_func = None
                patched += 1
                break
        logger.info("Nullified flash_attn_qkvpacked_func in %d module(s)", patched)

    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim

    def encode(self, sequences: list[str], batch_size: int = 32) -> np.ndarray:
        """Return an (N, 768) float32 embedding matrix."""
        import numpy as np
        import torch

        all_embeddings: list[np.ndarray] = []

        with torch.no_grad():
            for start in range(0, len(sequences), batch_size):
                batch = sequences[start : start + batch_size]
                inputs = self._tokenizer(
                    batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=MAX_LENGTH,
                ).to(self._device)

                hidden_states = self._model(**inputs)[0]
                pooled = torch.mean(hidden_states, dim=1)

                all_embeddings.append(pooled.cpu().float().numpy())
                done = min(start + batch_size, len(sequences))
                logger.info("Encoded %d/%d sequences", done, len(sequences))

        return np.vstack(all_embeddings)
