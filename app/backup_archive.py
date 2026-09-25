from __future__ import annotations

import json
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import __version__
from .db import Database


def create_backup_archive(
    db: Database,
    backups_dir: Path,
    *,
    prefix: str = "vps-bill",
) -> tuple[Path, Path, dict]:
    """Create a verified SQLite backup and a tar.gz bundle for Telegram/export.

    Returns (raw_db_path, archive_path, metadata). The raw .db is kept locally so
    existing restore tooling remains backward-compatible; the tar.gz is the
    portable copy sent to Telegram.
    """
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().astimezone()
    stamp = ts.strftime("%Y%m%d-%H%M%S")
    raw_path = backups_dir / f"{prefix}-{stamp}.db"
    archive_path = backups_dir / f"{prefix}-{stamp}.tar.gz"

    db.backup_to(raw_path)
    integrity = db.integrity()

    metadata = {
        "app": "vps-bill",
        "version": __version__,
        "created_at": ts.isoformat(timespec="seconds"),
        "database_file": "billing.db",
        "schema_version": integrity.get("schema_version"),
        "source_size": integrity.get("size"),
        "backup_size": raw_path.stat().st_size,
        "integrity": "ok",
    }

    with tempfile.TemporaryDirectory(prefix="vps-bill-backup-") as tmp:
        tmpdir = Path(tmp)
        metadata_path = tmpdir / "metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(raw_path, arcname="billing.db")
            tar.add(metadata_path, arcname="metadata.json")

    if not archive_path.exists() or archive_path.stat().st_size <= 0:
        raise RuntimeError("backup archive was not created")

    return raw_path, archive_path, metadata



def delete_old_backup_files(backups_dir: Path, *, days: int = 30) -> tuple[int, int, int]:
    """Delete local .db and .tar.gz backup files older than ``days``.

    Returns (removed, failed, freed_bytes). Newer backups and unrelated files
    are left untouched.
    """
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max(1, int(days)) * 86400

    removed = 0
    failed = 0
    freed_bytes = 0

    for path in backups_dir.iterdir():
        if not path.is_file():
            continue
        if not (path.suffix == ".db" or path.name.endswith(".tar.gz")):
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        if stat.st_mtime >= cutoff:
            continue
        try:
            size = stat.st_size
            path.unlink()
            removed += 1
            freed_bytes += size
        except FileNotFoundError:
            pass
        except OSError:
            failed += 1

    return removed, failed, freed_bytes

def delete_all_backup_files(backups_dir: Path) -> tuple[int, int]:
    """Delete all local .db and .tar.gz backup files in backups_dir.

    Returns (removed, failed). Non-backup files are left untouched.
    """
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    files = [
        p for p in backups_dir.iterdir()
        if p.is_file() and (p.suffix == ".db" or p.name.endswith(".tar.gz"))
    ]
    removed = 0
    failed = 0
    for path in files:
        try:
            path.unlink()
            removed += 1
        except FileNotFoundError:
            pass
        except OSError:
            failed += 1
    return removed, failed
