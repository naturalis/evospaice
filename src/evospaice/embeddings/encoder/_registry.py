"""Model-family registry and factory."""

from __future__ import annotations

from typing import Any

from encoder._base import SequenceEncoder

REGISTRY: dict[str, type] = {}


def register(name: str):
    """Class decorator that registers an encoder under *name*."""

    def decorator(cls: type) -> type:
        REGISTRY[name] = cls
        return cls

    return decorator


def create_encoder(family: str, **kwargs: Any) -> SequenceEncoder:
    """Instantiate an encoder by family name."""
    if family not in REGISTRY:
        available = ", ".join(sorted(REGISTRY))
        raise ValueError(f"Unknown model family '{family}'. Available: {available}")
    return REGISTRY[family](**kwargs)
