"""Structured request logging with correlation ids.

Every request emits one JSON line: method, path, endpoint, status,
duration, the authenticated actor, and the correlation id that also
rides the ``X-Request-ID`` response header and every audit event the
request wrote. Log lines never carry request bodies, query strings, or
cookies — those can contain secrets.
"""

from __future__ import annotations

import json
import logging
import sys
import time


class JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "at": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("correlation_id", "actor", "method", "path",
                    "endpoint", "status", "duration_ms",
                    "application_version", "build_commit"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            payload["exception"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False)


def configure_structured_logging(level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("atlas")
    if not any(
        isinstance(h, logging.StreamHandler)
        and isinstance(h.formatter, JsonLineFormatter)
        for h in logger.handlers
    ):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonLineFormatter())
        logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False
    return logger


def register_observability(app) -> None:
    from flask import g, request

    logger = configure_structured_logging(
        str(app.config.get("ATLAS_LOG_LEVEL") or "INFO")
    )
    app.config["ATLAS_LOGGER"] = logger
    from founderos_atlas.release import VERSION, build_commit

    logger.info(
        "startup",
        extra={"application_version": VERSION, "build_commit": build_commit()},
    )

    @app.after_request
    def _log_request(response):
        try:
            started = getattr(g, "request_started", None)
            duration_ms = (
                round((time.perf_counter() - started) * 1000, 1)
                if started else None
            )
            principal = getattr(g, "principal", None)
            logger.info(
                "request",
                extra={
                    "correlation_id": getattr(g, "correlation_id", None),
                    "actor": principal.username if principal else None,
                    "method": request.method,
                    "path": request.path,
                    "endpoint": request.endpoint,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        except Exception:  # pragma: no cover - logging must never break a page
            pass
        return response
