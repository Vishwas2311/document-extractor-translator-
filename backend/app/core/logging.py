import logging
import sys
from typing import Any, cast

import structlog

_SENSITIVE_LOG_KEYS = {
    "password",
    "api_key",
    "authorization",
    "token",
    "secret",
    "access_token",
    "refresh_token",
}


def _redact_sensitive(
    _logger: object, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Belt-and-suspenders: no call site currently logs a secret (verified by audit),
    but this scrubs any event field whose *key name* matches a known-sensitive term
    before it reaches the renderer, so a future accidental `logger.info(api_key=...)`
    fails safe instead of landing in plaintext logs. Exact key-name match only - not a
    value-pattern scanner - to avoid false positives mangling unrelated fields."""
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_LOG_KEYS:
            event_dict[key] = "***redacted***"
    return event_dict


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    processors: list[object] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _redact_sensitive,
    ]
    processors.append(
        structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=cast(Any, processors),
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
