from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("_") or key in {
                "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
                "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
                "created", "msecs", "relativeCreated", "thread", "threadName", "processName",
                "process", "message",
            }:
                continue
            payload[key] = value
        return json.dumps(payload, default=_json_default)


def configure_json_logging(level: int = logging.INFO) -> None:
    formatter = JsonFormatter()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)

    for name in ("fastmcp", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.propagate = True
        for existing in logger.handlers[:]:
            logger.removeHandler(existing)
