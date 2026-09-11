"""AML / MLflow logging utilities."""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)


class AMLLogger:
    """Logger that uses MLflow when running inside an Azure ML Job, otherwise prints to stderr."""

    def __init__(self) -> None:
        self._tracking_uri = os.getenv("MLFLOW_TRACKING_URI", None)
        self._mlflow = None
        if self._tracking_uri:
            try:
                import mlflow

                mlflow.set_tracking_uri(self._tracking_uri)
                self._mlflow = mlflow
            except Exception as exc:
                logger.warning("MLflow init failed, falling back to stderr: %s", exc)

    def set_tags(self, tags: dict[str, str]) -> None:
        if self._mlflow:
            self._mlflow.set_tags(tags)
        else:
            for name, value in tags.items():
                print(f"tag:{name}={value}", file=sys.stderr)

    def log_metrics(self, metrics: dict[str, int | float]) -> None:
        if self._mlflow:
            self._mlflow.log_metrics(metrics)
        else:
            for name, value in metrics.items():
                print(f"metric:{name}={value}", file=sys.stderr)
