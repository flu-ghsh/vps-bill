import json
import tarfile
from pathlib import Path

from app.backup_archive import create_backup_archive, delete_old_backup_files
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


def test_delete_old_backup_files_removes_only_files_older_than_30_days(tmp_path: Path):
    import os
    import time

    old_db = tmp_path / "vps-bill-old.db"
    old_tar = tmp_path / "vps-bill-old.tar.gz"
    fresh_db = tmp_path / "vps-bill-fresh.db"
    fresh_tar = tmp_path / "vps-bill-fresh.tar.gz"
    keep_txt = tmp_path / "keep.txt"

    for path in (old_db, old_tar, fresh_db, fresh_tar, keep_txt):
        path.write_bytes(b"x" * 1024)

    old_time = time.time() - 31 * 86400
    os.utime(old_db, (old_time, old_time))
    os.utime(old_tar, (old_time, old_time))

    removed, failed, freed_bytes = delete_old_backup_files(tmp_path, days=30)

    assert removed == 2
    assert failed == 0
    assert freed_bytes == 2048
    assert not old_db.exists()
    assert not old_tar.exists()
    assert fresh_db.exists()
    assert fresh_tar.exists()
    assert keep_txt.exists()
