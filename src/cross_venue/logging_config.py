"""Central logging configuration for project tools and future collectors."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TextIO, override

from cross_venue.config import ProjectSettings

_HANDLER_MARKER = "_cross_venue_handler"


class StructuredUTCFormatter(logging.Formatter):
    """Format log records with stable UTC fields."""

    def __init__(self, *, environment: str, component: str) -> None:
        super().__init__()
        self.environment = environment
        self.component = component

    @override
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Return an ISO-8601 UTC timestamp."""

        del datefmt
        return datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")

    def format(self, record: logging.LogRecord) -> str:
        """Return a compact structured log line."""

        message = record.getMessage()
        return (
            f"timestamp={self.formatTime(record)} "
            f"level={record.levelname} "
            f"logger={record.name} "
            f"environment={self.environment} "
            f"component={self.component} "
            f"message={message}"
        )


def configure_logging(
    settings: ProjectSettings | None = None,
    *,
    component: str = "application",
    logger_name: str = "cross_venue",
    stream: TextIO | None = None,
    force: bool = False,
) -> logging.Logger:
    """Configure and return the project logger.

    Repeated calls update the existing project handler instead of adding duplicate
    handlers. Tests may pass ``force=True`` to replace the handler stream.
    """

    resolved_settings = settings or ProjectSettings()
    logger = logging.getLogger(logger_name)
    logger.setLevel(resolved_settings.log_level)
    logger.propagate = False

    existing_handlers = [
        handler for handler in logger.handlers if getattr(handler, _HANDLER_MARKER, False)
    ]
    if force:
        for handler in existing_handlers:
            logger.removeHandler(handler)
        existing_handlers = []

    formatter = StructuredUTCFormatter(
        environment=resolved_settings.environment,
        component=component,
    )

    if existing_handlers:
        handler = existing_handlers[0]
        handler.setLevel(resolved_settings.log_level)
        handler.setFormatter(formatter)
        return logger

    handler = logging.StreamHandler(stream)
    setattr(handler, _HANDLER_MARKER, True)
    handler.setLevel(resolved_settings.log_level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger
