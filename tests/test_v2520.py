from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_version_2520():
    assert "## 2.5.20" in (ROOT / "CHANGELOG.md").read_text()


def test_dictionaries_has_own_emoji_slot_and_button():
    ui = (ROOT / "app" / "ui.py").read_text()
    handlers = (ROOT / "app" / "handlers.py").read_text()
    assert '"dictionaries": ("📚", "Справочники")' in ui
    assert 'button(emojis, "dictionaries", "Справочники", "settings:dictionaries")' in ui
    assert "e(self.emojis, 'dictionaries')" in handlers


def test_provider_and_tag_dictionary_items_use_their_icons():
    ui = (ROOT / "app" / "ui.py").read_text()
    assert 'slot = "provider" if kind == "provider" else "tags" if kind == "tag" else None' in ui
    assert 'row.append(button(emojis, slot, limited[idx], f"dict:item:{kind}:{idx}"))' in ui


def test_payment_reminder_contains_optional_vps_note():
    notifier = (ROOT / "app" / "notifier.py").read_text()
    assert 'note = str(s.get("notes") or "").strip()' in notifier
    assert 'Заметка: {h(note)}' in notifier
    assert 'if note else ""' in notifier
