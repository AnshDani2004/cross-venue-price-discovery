from io import StringIO

from cross_venue.config import ProjectSettings
from cross_venue.logging_config import configure_logging


def test_configure_logging_emits_structured_utc_message() -> None:
    stream = StringIO()
    logger = configure_logging(
        ProjectSettings(environment="test", log_level="INFO"),
        component="unit-test",
        stream=stream,
        force=True,
    )

    logger.info("hello")
    output = stream.getvalue()

    assert "timestamp=" in output
    assert "+00:00" in output
    assert "level=INFO" in output
    assert "logger=cross_venue" in output
    assert "environment=test" in output
    assert "component=unit-test" in output
    assert "message=hello" in output


def test_configure_logging_respects_configured_level() -> None:
    stream = StringIO()
    logger = configure_logging(
        ProjectSettings(environment="test", log_level="WARNING"),
        component="unit-test",
        stream=stream,
        force=True,
    )

    logger.info("hidden")
    logger.warning("visible")

    output = stream.getvalue()
    assert "hidden" not in output
    assert "visible" in output


def test_configure_logging_does_not_add_duplicate_handlers() -> None:
    stream = StringIO()
    settings = ProjectSettings(environment="test", log_level="INFO")
    logger = configure_logging(settings, component="unit-test", stream=stream, force=True)
    handler_count = len(logger.handlers)

    configure_logging(settings, component="unit-test", stream=stream)

    assert len(logger.handlers) == handler_count


def test_configure_logging_does_not_include_secrets_by_default() -> None:
    stream = StringIO()
    logger = configure_logging(
        ProjectSettings(environment="test", log_level="INFO"),
        component="unit-test",
        stream=stream,
        force=True,
    )

    logger.info("safe")
    output = stream.getvalue().lower()

    assert "api_key" not in output
    assert "password" not in output
    assert "secret" not in output
