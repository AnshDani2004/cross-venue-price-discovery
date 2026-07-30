"""Interrupted raw shard recovery."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from cross_venue.storage.archive_record import RawArchiveRecord
from cross_venue.storage.checksum import write_sha256_sidecar
from cross_venue.storage.exceptions import RecoveryError


@dataclass(frozen=True, slots=True)
class RecoveryAction:
    """One planned or applied recovery action."""

    partial_path: Path
    valid_records: int
    trailing_bytes: int
    applied: bool
    final_path: Path | None = None
    preserved_original_path: Path | None = None


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Recovery command result."""

    session_path: Path
    actions: tuple[RecoveryAction, ...]
    errors: tuple[str, ...] = ()

    @property
    def successful(self) -> bool:
        return not self.errors

    def to_text(self) -> str:
        status = "ok" if self.successful else "failed"
        lines = [f"Recovery status: {status}", f"Session path: {self.session_path}"]
        for action in self.actions:
            mode = "applied" if action.applied else "dry-run"
            lines.append(
                f"{mode}: {action.partial_path.name} valid_records={action.valid_records} "
                f"trailing_bytes={action.trailing_bytes}"
            )
        lines.extend(f"Error: {error}" for error in self.errors)
        return "\n".join(lines)


def recover_session(session_path: Path, *, apply: bool = False) -> RecoveryResult:
    """Recover partial shards in one session directory."""

    raw_dir = session_path / "raw"
    if not raw_dir.exists():
        return RecoveryResult(
            session_path=session_path,
            actions=(),
            errors=("raw directory missing",),
        )
    actions: list[RecoveryAction] = []
    errors: list[str] = []
    for partial_path in sorted(raw_dir.glob("*.partial")):
        try:
            valid_lines, trailing = _scan_partial(partial_path)
            final_name = partial_path.name.removesuffix(".partial")
            final_path = partial_path.with_name(final_name)
            original_path = partial_path.with_name(f"{partial_path.name}.original")
            if apply:
                if not original_path.exists():
                    partial_path.replace(original_path)
                else:
                    shutil.copy2(partial_path, original_path)
                    partial_path.unlink()
                with final_path.open("w", encoding="utf-8") as file_handle:
                    file_handle.writelines(valid_lines)
                write_sha256_sidecar(final_path)
            actions.append(
                RecoveryAction(
                    partial_path=partial_path,
                    valid_records=len(valid_lines),
                    trailing_bytes=len(trailing),
                    applied=apply,
                    final_path=final_path if apply else None,
                    preserved_original_path=original_path if apply else None,
                )
            )
        except Exception as exc:
            errors.append(f"{partial_path.name}: {exc}")
    return RecoveryResult(session_path=session_path, actions=tuple(actions), errors=tuple(errors))


def _scan_partial(path: Path) -> tuple[list[str], bytes]:
    data = path.read_bytes()
    if not data:
        return [], b""
    lines = data.splitlines(keepends=True)
    trailing = b""
    if not data.endswith(b"\n"):
        trailing = lines.pop() if lines else data
    valid_lines: list[str] = []
    for line in lines:
        decoded = line.decode("utf-8")
        RawArchiveRecord.from_json_line(decoded)
        valid_lines.append(decoded)
    if trailing:
        try:
            RawArchiveRecord.from_json_line(trailing.decode("utf-8"))
        except Exception:
            pass
        else:
            raise RecoveryError("trailing record is valid but missing newline")
    return valid_lines, trailing
