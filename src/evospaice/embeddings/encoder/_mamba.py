"""BarcodeMamba+ encoder adapter (384D, 2-layer SSM).

Requirements (optional dependency group ``mamba``):
    mamba-ssm, causal-conv1d
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import numpy as np

from evospaice.embeddings.encoder._registry import register

if TYPE_CHECKING:
    import torch


@register("mamba")
class MambaEncoder:
    """BarcodeMamba+ (384D, 2-layer SSM)."""

    def __init__(self, checkpoint: str = "BarcodeMamba-dim384-layer2-char/checkpoints/last.ckpt", model_name: str = None, device: str = None, **kwargs) -> None:
        try:
            import torch as _torch
            from mamba_ssm.models.mixer_seq_simple import MambaLMHeadModel
            from mamba_ssm.models.config_mamba import MambaConfig
        except ImportError:
            raise ImportError(
                "MambaEncoder requires 'torch', 'mamba-ssm' and 'causal-conv1d'. "
                "Install them or use an environment that provides them."
            )

        if model_name is not None and model_name != "BarcodeMamba":
            # Allow fallback if model_name is passed as checkpoint path
            if os.path.exists(model_name):
                checkpoint = model_name

        self.device = device or ("cuda" if _torch.cuda.is_available() else "cpu")
        self.dna_vocab = "ACGTNRYWSKMB"
        self.tokenizer = {c: i for i, c in enumerate(self.dna_vocab)}
        self.max_seq_len = 660

        config = MambaConfig(d_model=384, n_layer=2, vocab_size=len(self.dna_vocab), ssm_cfg={'d_state': 16})
        self.model = MambaLMHeadModel(config, device=self.device)

        state_dict = _torch.load(checkpoint, map_location=self.device, weights_only=True)
        if 'state_dict' in state_dict: 
            state_dict = state_dict['state_dict']

        # Strip lightning/backbone prefixes to match standard MambaLMHeadModel
        sd = {k.replace('model.', '').replace('backbone.', ''): v for k, v in state_dict.items()}
        self.model.load_state_dict(sd, strict=False)
        self.model.eval()

    @property
    def embedding_dim(self) -> int:
        return 384

    def encode(self, sequences: list[str], batch_size: int = 1024) -> np.ndarray:
        import torch

        all_embeddings = []
        for i in range(0, len(sequences), batch_size):
            batch_seqs = sequences[i:i + batch_size]
            max_len = max(len(s) for s in batch_seqs)
            # Clip to a global max if necessary, or just use batch max
            # Using max_seq_len as upper bound to prevent OOM
            batch_max_len = min(max_len, self.max_seq_len) if hasattr(self, 'max_seq_len') and self.max_seq_len else max_len

            t = torch.full((len(batch_seqs), batch_max_len), 4, dtype=torch.long, device=self.device)
            lengths = []
            
            for j, s in enumerate(batch_seqs):
                ids = [self.tokenizer.get(base, 4) for base in s.upper()]
                length = min(len(ids), batch_max_len)
                if length > 0:
                    t[j, :length] = torch.tensor(ids[:length], device=self.device)
                lengths.append(max(length, 1)) # avoid division by zero
            
            lengths_tensor = torch.tensor(lengths, device=self.device, dtype=torch.float32).unsqueeze(1)
            
            with torch.no_grad():
                with torch.amp.autocast(device_type='cuda' if 'cuda' in self.device else 'cpu'):
                    hidden_states = self.model.backbone(t)
                    # Mask out padding tokens
                    mask = torch.arange(batch_max_len, device=self.device).expand(len(batch_seqs), batch_max_len) < torch.tensor(lengths, device=self.device).unsqueeze(1)
                    hidden_states = hidden_states * mask.unsqueeze(-1)
                    emb = hidden_states.sum(dim=1) / lengths_tensor
            
            all_embeddings.append(emb.cpu().numpy().astype('float32'))
            
        return np.concatenate(all_embeddings, axis=0)
