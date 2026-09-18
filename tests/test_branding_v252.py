from pathlib import Path

from app.backup_archive import create_backup_archive
from app.db import Database


def test_backup_default_prefix_is_vps_bill(tmp_path: Path):
    db = Database(tmp_path / "data" / "billing.db")
    raw, archive, _ = create_backup_archive(db, tmp_path / "backups")
    assert raw.name.startswith("vps-bill-")
    assert archive.name.startswith("vps-bill-")


def test_default_buttons_are_primary_and_reminder_is_renamed():
    source = (Path(__file__).parents[1] / "app" / "ui.py").read_text(encoding="utf-8")
    assert '"Стандарт 7 / 3 / 1 / 0"' not in source
    assert '"По умолчанию", "currency:default", style="primary"' in source
    assert '"По умолчанию", "billcycle:default", style="primary"' in source
    assert '"По умолчанию", "rem:default", style="primary"' in source
