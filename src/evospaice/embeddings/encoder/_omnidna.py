"""OmniDNA encoder adapter (20M – 1B)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from evospaice.embeddings.encoder._registry import register

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "zehui127/Omni-DNA-20M"
MAX_LENGTH = 1024  # Omni-DNA context window (250 tokens × 4-mer ≈ 1000 nt)

MODELS = {
    "20m": "zehui127/Omni-DNA-20M",
    "60m": "zehui127/Omni-DNA-60M",
    "116m": "zehui127/Omni-DNA-116M",
    "300m": "zehui127/Omni-DNA-300M",
    "700m": "zehui127/Omni-DNA-700M",
    "1b": "zehui127/Omni-DNA-1B",
}


@register("omnidna")
class OmniDNAEncoder:
    """OmniDNA family encoder (20M – 1B)."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str = "cpu") -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._device = torch.device(device)
        self._tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        self._model = AutoModelForCausalLM.from_pretrained(
            model_name, trust_remote_code=True
        ).to(self._device)
        self._model.eval()
        self._compiled = False
        if self._device.type == "cuda":
            try:
                self._model = torch.compile(self._model)
                self._compiled = True
            except Exception:
                logger.warning("torch.compile unavailable, using eager mode")
        self._embedding_dim: int = self._model.config.hidden_size

    @property
    def embedding_dim(self) -> int:
        return self._embedding_dim

    def encode(self, sequences: list[str], batch_size: int = 64) -> np.ndarray:
        """Return an (N, D) float32 embedding matrix."""
        import numpy as np
        import torch

        all_embeddings: list[np.ndarray] = []
        batches = [
            sequences[i : i + batch_size]
            for i in range(0, len(sequences), batch_size)
        ]

        def tokenize_batch(batch: list[str]):
            return self._tokenizer(
                batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_token_type_ids=False,
            )

        with torch.no_grad(), ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(tokenize_batch, batches[0])

            for i in range(len(batches)):
                inputs = future.result().to(self._device, non_blocking=True)

                if i + 1 < len(batches):
                    future = executor.submit(tokenize_batch, batches[i + 1])

                try:
                    outputs = self._model(**inputs, output_hidden_states=True)
                except Exception:
                    if self._compiled:
                        import torch._dynamo

                        logger.warning(
                            "torch.compile failed during tracing, "
                            "falling back to eager mode"
                        )
                        torch._dynamo.reset()
                        self._model = self._model._orig_mod
                        self._compiled = False
                        outputs = self._model(**inputs, output_hidden_states=True)
                    else:
                        raise
                hidden = outputs.hidden_states[-1]

                mask = inputs["attention_mask"].unsqueeze(-1)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)

                all_embeddings.append(pooled.cpu().float().numpy())
                done = min((i + 1) * batch_size, len(sequences))
                logger.info("Encoded %d/%d sequences", done, len(sequences))

        return np.vstack(all_embeddings)
