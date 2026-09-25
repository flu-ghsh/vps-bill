from pathlib import Path


def test_v2516_server_name_edit_and_clean_details_ui():
    root = Path(__file__).resolve().parents[1]
    handlers = (root / "app" / "handlers.py").read_text(encoding="utf-8")
    ui = (root / "app" / "ui.py").read_text(encoding="utf-8")
    db = (root / "app" / "db.py").read_text(encoding="utf-8")

    assert '"name", "ip", "country", "purpose", "tags", "notes"' in db
    assert '"Имя", f"editfield:{server_id}:name"' in ui
    assert '"К карточке", f"editback:{server_id}"' in ui
    assert 'register(self.edit_server_back, F.data.startswith("editback:"))' in handlers
    assert 'field not in {"name", "ip", "country", "tags", "notes", "tag_add"}' in handlers
    assert "Нажми поле, чтобы изменить. Для очистки отправь" not in handlers
    assert 'reply_markup=server_edit_back_keyboard(sid, self.emojis)' in handlers


def test_v2516_version_and_changelog():
    root = Path(__file__).resolve().parents[1]
    assert "## 2.5.16" in (root / "CHANGELOG.md").read_text()
