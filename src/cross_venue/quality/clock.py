"""Read-only host-clock observation helpers."""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ClockObservationStatus(StrEnum):
    """Status for one read-only host-clock observation command."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TIMED_OUT = "TIMED_OUT"
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"


Runner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]

PROHIBITED_TOKENS = {
    "sudo",
    "sntp",
    "ntpdate",
    "-s",
    "-S",
    "--set",
    "set-time",
    "set-ntp",
    "clock_settime",
}


def observe_host_clock(
    *,
    runner: Runner | None = None,
    platform_name: str | None = None,
    timeout_seconds: float = 5,
) -> dict[str, Any]:
    """Collect best-effort host-clock status without changing system time."""

    observed_at = datetime.now(UTC).isoformat()
    system = platform_name or platform.system()
    commands = _commands_for_platform(system)
    if not commands:
        return {
            "platform": system,
            "observed_at": observed_at,
            "overall_status": ClockObservationStatus.UNSUPPORTED_PLATFORM.value,
            "offset_status": "host clock offset unavailable",
            "observations": [],
        }
    observations = [
        _run_observation(command, runner=runner, timeout_seconds=timeout_seconds)
        for command in commands
    ]
    statuses = [item["status"] for item in observations]
    overall = (
        ClockObservationStatus.AVAILABLE.value
        if ClockObservationStatus.AVAILABLE.value in statuses
        else statuses[0]
        if statuses
        else ClockObservationStatus.UNAVAILABLE.value
    )
    return {
        "platform": system,
        "observed_at": observed_at,
        "overall_status": overall,
        "offset_status": "host clock offset unavailable",
        "observations": observations,
    }


def ensure_read_only_clock_command(command: Sequence[str]) -> None:
    """Reject privileged or clock-mutating commands before invocation."""

    lowered = {part.lower() for part in command}
    if lowered & PROHIBITED_TOKENS:
        raise ValueError("clock observation command contains prohibited clock-setting token")
    if any(part.lower().startswith("-s") for part in command):
        raise ValueError("clock observation command contains prohibited clock-setting option")
    if any("sudo" in part.lower() for part in command):
        raise ValueError("clock observation command must not use sudo")


def _commands_for_platform(system: str) -> list[list[str]]:
    if system == "Darwin":
        return [
            ["systemsetup", "-getusingnetworktime"],
            ["systemsetup", "-getnetworktimeserver"],
        ]
    if system == "Linux":
        return [
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            ["timedatectl", "show", "-p", "NTP", "--value"],
        ]
    return []


def _run_observation(
    command: Sequence[str],
    *,
    runner: Runner | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    ensure_read_only_clock_command(command)
    run = runner or _default_runner
    try:
        result = run(command, timeout_seconds)
    except FileNotFoundError:
        return _observation(command, ClockObservationStatus.COMMAND_NOT_FOUND)
    except subprocess.TimeoutExpired:
        return _observation(command, ClockObservationStatus.TIMED_OUT)
    except OSError as exc:
        return _observation(command, ClockObservationStatus.UNAVAILABLE, error=str(exc))
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    combined = f"{stdout}\n{stderr}".lower()
    if (
        "administrator" in combined
        or "permission denied" in combined
        or "not permitted" in combined
    ):
        status = ClockObservationStatus.PERMISSION_DENIED
    elif result.returncode != 0:
        status = ClockObservationStatus.UNAVAILABLE
    elif not stdout and not stderr:
        status = ClockObservationStatus.PARSE_ERROR
    else:
        status = ClockObservationStatus.AVAILABLE
    return _observation(
        command,
        status,
        returncode=result.returncode,
        stdout=stdout[:500],
        stderr=stderr[:500],
    )


def _default_runner(
    command: Sequence[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


def _observation(
    command: Sequence[str],
    status: ClockObservationStatus,
    *,
    returncode: int | None = None,
    stdout: str = "",
    stderr: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command": list(command),
        "status": status.value,
        "command_available": status
        not in {
            ClockObservationStatus.COMMAND_NOT_FOUND,
            ClockObservationStatus.UNSUPPORTED_PLATFORM,
        },
        "observation_successful": status == ClockObservationStatus.AVAILABLE,
        "returncode": returncode,
        "stdout_classification": _classify_output(stdout),
        "stderr_classification": _classify_output(stderr),
        "stdout": stdout,
        "stderr": stderr,
    }
    if error is not None:
        payload["error"] = error
    return payload


def _classify_output(output: str) -> str:
    lowered = output.lower()
    if not output:
        return "empty"
    if "administrator" in lowered or "permission denied" in lowered or "not permitted" in lowered:
        return "permission_denied"
    if "yes" in lowered or "true" in lowered or "network time" in lowered:
        return "clock_status"
    return "unparsed"
