import json
import tarfile
from pathlib import Path

from app.backup_archive import create_backup_archive
from app.db import Database


def test_backup_archive_contains_db_and_metadata(tmp_path: Path):
    db = Database(tmp_path / "data" / "billing.db")
    db.add_server(
        name="test-vps",
        provider="TestHost",
        amount_minor=1000,
        currency="RUB",
        next_due="2026-09-30",
        cycle="monthly",
    )

    raw, archive, meta = create_backup_archive(db, tmp_path / "backups")

    assert raw.exists()
    assert archive.exists()
    assert meta["integrity"] == "ok"

    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
        assert "billing.db" in names
        assert "metadata.json" in names
        metadata = json.load(tar.extractfile("metadata.json"))
        assert metadata["app"] == "vps-bill"
        assert metadata["schema_version"] >= 1
