"""encoder — pluggable DNA sequence encoding with multiple model families."""

from encoder._base import SequenceEncoder
from encoder._fasta import parse_fasta
from encoder._registry import REGISTRY, create_encoder

# Adapter modules register themselves on import.  Import them here so that
# ``create_encoder`` works out of the box.  Heavy runtime deps (torch,
# transformers) are deferred to adapter __init__/encode methods.
import encoder._omnidna  # noqa: F401
import encoder._mamba  # noqa: F401
import encoder._dnabert  # noqa: F401

__all__ = ["SequenceEncoder", "parse_fasta", "create_encoder", "REGISTRY"]