from __future__ import annotations

import subprocess
from collections.abc import Sequence

import pytest

from cross_venue.quality.clock import (
    ClockObservationStatus,
    ensure_read_only_clock_command,
    observe_host_clock,
)


def test_clock_observation_successful_read_only_linux_command() -> None:
    def runner(command: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(command), 0, stdout="yes\n", stderr="")

    result = observe_host_clock(runner=runner, platform_name="Linux")

    assert result["overall_status"] == ClockObservationStatus.AVAILABLE
    assert result["observations"][0]["observation_successful"] is True


def test_clock_observation_treats_admin_required_output_as_permission_denied() -> None:
    def runner(command: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            list(command),
            0,
            stdout="You need administrator access to run this tool\n",
            stderr="",
        )

    result = observe_host_clock(runner=runner, platform_name="Darwin")

    assert result["overall_status"] == ClockObservationStatus.PERMISSION_DENIED
    assert result["observations"][0]["command_available"] is True
    assert result["observations"][0]["observation_successful"] is False


def test_clock_observation_permission_denied_stderr() -> None:
    def runner(command: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(command), 1, stdout="", stderr="Permission denied")

    result = observe_host_clock(runner=runner, platform_name="Linux")

    assert result["overall_status"] == ClockObservationStatus.PERMISSION_DENIED


def test_clock_observation_command_missing_and_timeout() -> None:
    def missing(_command: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError

    def timeout(command: Sequence[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(list(command), timeout_seconds)

    assert observe_host_clock(runner=missing, platform_name="Linux")["overall_status"] == (
        ClockObservationStatus.COMMAND_NOT_FOUND
    )
    assert observe_host_clock(runner=timeout, platform_name="Linux")["overall_status"] == (
        ClockObservationStatus.TIMED_OUT
    )


def test_clock_observation_parse_error_and_unsupported_platform() -> None:
    def empty(command: Sequence[str], _timeout: float) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(command), 0, stdout="", stderr="")

    assert observe_host_clock(runner=empty, platform_name="Linux")["overall_status"] == (
        ClockObservationStatus.PARSE_ERROR
    )
    assert observe_host_clock(platform_name="Plan9")["overall_status"] == (
        ClockObservationStatus.UNSUPPORTED_PLATFORM
    )


def test_clock_observation_rejects_privileged_or_setting_commands() -> None:
    for command in (
        ["sudo", "timedatectl", "show"],
        ["sntp", "-sS", "time.apple.com"],
        ["timedatectl", "set-time", "2026-01-01"],
        ["clock_settime"],
    ):
        with pytest.raises(ValueError):
            ensure_read_only_clock_command(command)
