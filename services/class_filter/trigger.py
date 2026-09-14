"""Trigger-file contract for FASTA filtering jobs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_TARGET_CLASS = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class TriggerRequest:
    source_blob_url: str
    target_class: str

    @property
    def output_blob_name(self) -> str:
        return f"{self.target_class.lower()}.fasta"

    @classmethod
    def from_json(cls, payload: bytes) -> TriggerRequest:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Trigger file must contain a JSON object")

        values: dict[str, str] = {}
        for field_name in ("source_blob_url", "target_class"):
            value = data.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Trigger file must contain a non-empty {field_name}")
            values[field_name] = value.strip()

        if not _TARGET_CLASS.fullmatch(values["target_class"]):
            raise ValueError(
                "target_class must start with a letter and contain only letters, "
                "numbers, underscores, or hyphens"
            )

        return cls(**values)