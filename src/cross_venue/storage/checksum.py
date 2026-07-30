"""SHA-256 helpers for finalized archive shards."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cross_venue.storage.exceptions import ChecksumError


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest for a file."""

    digest = hashlib.sha256()
    try:
        with path.open("rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ChecksumError(f"could not checksum {path.name}") from exc
    return digest.hexdigest()


def write_sha256_sidecar(path: Path) -> str:
    """Write ``<sha256>  <filename>`` sidecar for a finalized shard."""

    digest = sha256_file(path)
    sidecar = path.with_name(f"{path.name}.sha256")
    try:
        sidecar.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    except OSError as exc:
        raise ChecksumError(f"could not write checksum sidecar for {path.name}") from exc
    return digest


def verify_sha256_sidecar(path: Path) -> bool:
    """Verify a finalized shard against its sidecar."""

    sidecar = path.with_name(f"{path.name}.sha256")
    if not sidecar.exists():
        raise ChecksumError(f"missing checksum sidecar for {path.name}")
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    actual = sha256_file(path)
    if expected != actual:
        raise ChecksumError(f"checksum mismatch for {path.name}")
    return True
