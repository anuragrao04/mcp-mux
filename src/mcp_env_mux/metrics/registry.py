from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from mcp_env_mux.metrics.config import MetricsConfig


@dataclass
class Metrics:
    config: MetricsConfig
    registry: CollectorRegistry
    tool_requests_total: Counter
    tool_request_success_total: Counter
    tool_request_errors_total: Counter
    tool_request_duration_seconds: Histogram
    tool_requests_in_flight: Gauge
    user_tool_calls_total: Counter
    auth_requests_total: Counter
    rbac_decisions_total: Counter
    ui_requests_total: Counter
    ui_request_duration_seconds: Histogram
    ui_logins_total: Counter
    ui_token_mint_total: Counter
    configured_environments: Gauge
    merged_tools: Gauge
    merge_warnings_total: Gauge
    merge_errors_total: Gauge
    backend_discovery_duration_seconds: Histogram
    backend_discovery_success_total: Counter
    backend_discovery_errors_total: Counter

    @property
    def enabled(self) -> bool:
        return self.config.enabled


def create_metrics(config: MetricsConfig) -> Metrics:
    registry = CollectorRegistry()
    return Metrics(
        config=config,
        registry=registry,
        tool_requests_total=Counter(
            "mcp_env_mux_tool_requests_total",
            "Total tool call attempts routed through the proxy.",
            ["tool", "env", "principal_type"],
            registry=registry,
        ),
        tool_request_success_total=Counter(
            "mcp_env_mux_tool_request_success_total",
            "Successful tool calls.",
            ["tool", "env", "principal_type"],
            registry=registry,
        ),
        tool_request_errors_total=Counter(
            "mcp_env_mux_tool_request_errors_total",
            "Failed tool calls bucketed by normalized error type.",
            ["tool", "env", "principal_type", "error_type"],
            registry=registry,
        ),
        tool_request_duration_seconds=Histogram(
            "mcp_env_mux_tool_request_duration_seconds",
            "End-to-end tool call latency through the proxy.",
            ["tool", "env", "principal_type"],
            registry=registry,
        ),
        tool_requests_in_flight=Gauge(
            "mcp_env_mux_tool_requests_in_flight",
            "Currently in-flight tool calls.",
            ["tool", "env"],
            registry=registry,
        ),
        user_tool_calls_total=Counter(
            "mcp_env_mux_user_tool_calls_total",
            "Total tool calls by user or bot identity.",
            ["principal", "principal_type"],
            registry=registry,
        ),
        auth_requests_total=Counter(
            "mcp_env_mux_auth_requests_total",
            "Authentication verification attempts and outcomes.",
            ["token_type", "result", "reason"],
            registry=registry,
        ),
        rbac_decisions_total=Counter(
            "mcp_env_mux_rbac_decisions_total",
            "RBAC allow and deny decisions for tool calls.",
            ["tool", "env", "decision", "principal_type"],
            registry=registry,
        ),
        ui_requests_total=Counter(
            "mcp_env_mux_ui_requests_total",
            "UI route request counts.",
            ["route", "result"],
            registry=registry,
        ),
        ui_request_duration_seconds=Histogram(
            "mcp_env_mux_ui_request_duration_seconds",
            "UI route request latency.",
            ["route"],
            registry=registry,
        ),
        ui_logins_total=Counter(
            "mcp_env_mux_ui_logins_total",
            "Browser login flow outcomes.",
            ["result"],
            registry=registry,
        ),
        ui_token_mint_total=Counter(
            "mcp_env_mux_ui_token_mint_total",
            "Token mint attempts and outcomes.",
            ["result"],
            registry=registry,
        ),
        configured_environments=Gauge(
            "mcp_env_mux_configured_environments",
            "Configured environments.",
            registry=registry,
        ),
        merged_tools=Gauge(
            "mcp_env_mux_merged_tools",
            "Merged tools exposed by the proxy.",
            registry=registry,
        ),
        merge_warnings_total=Gauge(
            "mcp_env_mux_merge_warnings_total",
            "Merge warnings at startup.",
            registry=registry,
        ),
        merge_errors_total=Gauge(
            "mcp_env_mux_merge_errors_total",
            "Merge errors at startup.",
            registry=registry,
        ),
        backend_discovery_duration_seconds=Histogram(
            "mcp_env_mux_backend_discovery_duration_seconds",
            "Backend discovery latency per environment.",
            ["env"],
            registry=registry,
        ),
        backend_discovery_success_total=Counter(
            "mcp_env_mux_backend_discovery_success_total",
            "Successful backend discovery attempts.",
            ["env"],
            registry=registry,
        ),
        backend_discovery_errors_total=Counter(
            "mcp_env_mux_backend_discovery_errors_total",
            "Failed backend discovery attempts.",
            ["env", "error_type"],
            registry=registry,
        ),
    )
