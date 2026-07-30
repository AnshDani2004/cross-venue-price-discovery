from datetime import UTC, datetime
from pathlib import Path

import pytest

from cross_venue.schemas import Exchange
from cross_venue.storage.exceptions import StorageError
from cross_venue.storage.paths import (
    resolve_under_root,
    safe_path_component,
    session_paths,
    shard_name,
)


def test_session_paths_are_partitioned_and_safe(tmp_path: Path) -> None:
    paths = session_paths(
        archive_root=tmp_path,
        venue=Exchange.KRAKEN,
        canonical_instrument="BTC-USD",
        session_id="kraken/session id",
        started_at=datetime(2026, 7, 30, 21, 0, tzinfo=UTC),
    )

    assert paths.session_root == (
        tmp_path
        / "venue=kraken"
        / "instrument=BTC-USD"
        / "date=2026-07-30"
        / "session=kraken-session-id"
    )
    assert paths.manifest_path.name == "session_manifest.json"
    assert paths.quality_path.name == "quality_summary.json"


def test_path_helpers_reject_escape_and_bad_components(tmp_path: Path) -> None:
    assert safe_path_component("BTC/USD spot") == "BTC-USD-spot"
    assert shard_name(12) == "part-00012.jsonl"

    with pytest.raises(StorageError, match="unsafe empty"):
        safe_path_component("***")
    with pytest.raises(ValueError, match="nonnegative"):
        shard_name(-1)
    with pytest.raises(StorageError, match="escapes"):
        resolve_under_root(tmp_path, tmp_path.parent / "outside")
