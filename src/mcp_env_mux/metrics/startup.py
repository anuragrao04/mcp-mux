from __future__ import annotations

from mcp_env_mux.metrics.registry import Metrics


def record_startup_state(
    metrics: Metrics | None,
    *,
    environment_count: int,
    merged_tool_count: int,
    merge_warning_count: int,
    merge_error_count: int,
) -> None:
    if metrics is None or not metrics.enabled:
        return
    metrics.configured_environments.set(environment_count)
    metrics.merged_tools.set(merged_tool_count)
    metrics.merge_warnings_total.set(merge_warning_count)
    metrics.merge_errors_total.set(merge_error_count)
