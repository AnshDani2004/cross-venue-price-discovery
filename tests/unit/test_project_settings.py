from pathlib import Path

import pytest
from pydantic import ValidationError

from cross_venue.config import ProjectSettings, load_project_settings


def test_project_settings_safe_defaults() -> None:
    settings = ProjectSettings()

    assert settings.environment == "development"
    assert settings.timezone == "UTC"
    assert settings.data_directory == Path("data")
    assert settings.report_directory == Path("reports")
    assert settings.log_level == "INFO"


def test_project_settings_load_from_toml() -> None:
    settings = load_project_settings(Path("configs/project.toml"))

    assert settings.timezone == "UTC"
    assert settings.log_level == "INFO"


def test_project_settings_reject_invalid_timezone() -> None:
    with pytest.raises(ValidationError, match="unknown timezone"):
        ProjectSettings(timezone="Not/AZone")


def test_project_settings_reject_invalid_log_level() -> None:
    with pytest.raises(ValidationError):
        ProjectSettings(log_level="TRACE")  # type: ignore[arg-type]


def test_project_settings_reject_invalid_environment() -> None:
    with pytest.raises(ValidationError):
        ProjectSettings(environment="staging")  # type: ignore[arg-type]


def test_project_settings_reject_unknown_field() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProjectSettings.model_validate({"environment": "development", "unexpected": True})


def test_project_settings_missing_fields_use_safe_defaults() -> None:
    settings = ProjectSettings.model_validate({})

    assert settings.environment == "development"
    assert settings.timezone == "UTC"


def test_project_settings_resolve_paths_against_base_directory(tmp_path: Path) -> None:
    settings = ProjectSettings(data_directory=Path("data"), report_directory=Path("reports"))

    assert (
        settings.resolve_path(settings.data_directory, base_directory=tmp_path)
        == (tmp_path / "data").resolve()
    )
    assert (
        settings.resolve_path(settings.report_directory, base_directory=tmp_path)
        == (tmp_path / "reports").resolve()
    )


def test_project_settings_environment_overrides() -> None:
    settings = ProjectSettings.from_environment(
        {
            "CROSS_VENUE_ENV": "test",
            "CROSS_VENUE_TIMEZONE": "UTC",
            "CROSS_VENUE_LOG_LEVEL": "DEBUG",
            "CROSS_VENUE_DATA_DIRECTORY": "tmp-data",
            "CROSS_VENUE_REPORT_DIRECTORY": "tmp-reports",
        }
    )

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.data_directory == Path("tmp-data")
    assert settings.report_directory == Path("tmp-reports")
