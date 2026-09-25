from pathlib import Path


def test_v2517_ui_and_handlers_changes():
    root = Path(__file__).resolve().parents[1]
    ui = (root / "app" / "ui.py").read_text(encoding="utf-8")
    handlers = (root / "app" / "handlers.py").read_text(encoding="utf-8")

    assert '"Имя", f"editfield:{server_id}:name", style="success"' in ui
    assert 'days = (1, 3, 5, 10)' in ui
    assert 'times = ("10:00", "15:00", "20:00")' in ui
    assert '"Ввести день и время", "report:manual"' in ui
    assert '"Создать и прислать бекап"' in ui
    assert '"Удалить старые бекапы", "backup:cleanup", style="danger"' in ui
    assert 'icon_custom_emoji_id=cabinet_id or None' in ui
    assert 'button(self.emojis, "back", "Возврат", "settings:reports")' in handlers
    assert 'note = str(s.get("notes") or "").strip()' in handlers
    assert '📦 <b>Архив' not in handlers


def test_v2517_version_and_changelog():
    root = Path(__file__).resolve().parents[1]
    assert "## 2.5.18" in (root / "CHANGELOG.md").read_text()
