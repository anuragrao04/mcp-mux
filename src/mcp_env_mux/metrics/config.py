from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MetricsConfig:
    enabled: bool = True
    path: str = "/metrics"
    user_level_metrics: bool = False
