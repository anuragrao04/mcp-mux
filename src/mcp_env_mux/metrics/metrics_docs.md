# metrics/

## Purpose

Provides Prometheus instrumentation for mcp-env-mux, including request counts, success/error counters, latency histograms, in-flight gauges, and response-size histograms. Response-size estimation is lightweight and best-effort for common content shapes.

## Modules

- `config.py` — Metrics config dataclass.
- `registry.py` — Prometheus collector registration.
- `helpers.py` — Principal extraction and error normalization helpers.
- `http.py` — `/metrics` exposition route.
- `startup.py` — Startup gauges.
- `tooling.py` — Tool-call instrumentation.
- `auth.py` — Auth and RBAC metric helpers.
- `ui.py` — UI request instrumentation helpers.
