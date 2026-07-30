"""Archive validation for finalized raw sessions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cross_venue.storage.archive_record import RawArchiveRecord
from cross_venue.storage.checksum import sha256_file, verify_sha256_sidecar
from cross_venue.storage.exceptions import ChecksumError
from cross_venue.storage.manifest_store import load_manifest
from cross_venue.storage.quality_store import load_quality_summary


@dataclass(frozen=True, slots=True)
class ArchiveValidationResult:
    """Archive validation summary."""

    valid: bool
    session_path: Path
    shards_checked: int
    records_checked: int
    errors: tuple[str, ...] = ()

    def to_text(self) -> str:
        status = "valid" if self.valid else "invalid"
        lines = [
            f"Archive status: {status}",
            f"Session path: {self.session_path}",
            f"Shards checked: {self.shards_checked}",
            f"Records checked: {self.records_checked}",
        ]
        lines.extend(f"Error: {error}" for error in self.errors)
        return "\n".join(lines)


def validate_archive(session_path: Path) -> ArchiveValidationResult:
    """Validate manifest, quality summary, shards, counts, and checksums."""

    errors: list[str] = []
    records_checked = 0
    shards_checked = 0
    manifest_path = session_path / "manifest" / "session_manifest.json"
    quality_path = session_path / "quality" / "quality_summary.json"
    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        return ArchiveValidationResult(
            valid=False,
            session_path=session_path,
            shards_checked=0,
            records_checked=0,
            errors=(f"manifest invalid: {exc}",),
        )
    try:
        load_quality_summary(quality_path)
    except Exception as exc:
        errors.append(f"quality summary invalid: {exc}")

    expected_next_index = 0
    for shard in manifest.shards:
        if shard.is_partial:
            errors.append(f"manifest references partial shard: {shard.relative_path}")
            continue
        shard_path = session_path / shard.relative_path
        if not shard_path.exists():
            errors.append(f"missing shard: {shard.relative_path}")
            continue
        try:
            verify_sha256_sidecar(shard_path)
        except ChecksumError as exc:
            errors.append(str(exc))
        if shard.sha256 is not None:
            actual_digest = sha256_file(shard_path)
            if actual_digest != shard.sha256:
                errors.append(f"manifest sha256 mismatch for {shard.relative_path}")
        lines = shard_path.read_text(encoding="utf-8").splitlines()
        if len(lines) != shard.record_count:
            errors.append(f"record count mismatch for {shard.relative_path}")
        for line in lines:
            try:
                record = RawArchiveRecord.from_json_line(line)
            except Exception as exc:
                errors.append(f"invalid raw record in {shard.relative_path}: {exc}")
                continue
            if record.record_index != expected_next_index:
                errors.append(
                    "record index mismatch: "
                    f"expected {expected_next_index}, got {record.record_index}"
                )
                expected_next_index = record.record_index
            expected_next_index += 1
            records_checked += 1
        if shard.byte_size != shard_path.stat().st_size:
            errors.append(f"byte size mismatch for {shard.relative_path}")
        shards_checked += 1

    if records_checked != manifest.records_written:
        errors.append("manifest records_written does not match readable records")
    partial_files = tuple((session_path / "raw").glob("*.partial"))
    if partial_files:
        errors.append("unreported partial files remain")
    return ArchiveValidationResult(
        valid=not errors,
        session_path=session_path,
        shards_checked=shards_checked,
        records_checked=records_checked,
        errors=tuple(errors),
    )
