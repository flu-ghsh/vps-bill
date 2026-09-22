from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_server_buttons_no_two_arg_append_regression():
    src = (ROOT / 'app' / 'ui.py').read_text()
    assert 'rows.append([button(emojis, "server", "В архив", f"archiveask:{server_id}")])' in src
    assert 'rows.append([button(emojis, "trash", "В корзину", f"trashask:{server_id}", style="danger")])' in src
    assert 'rows.append([button(emojis, "server", "В архив", f"archiveask:{server_id}")],' not in src


def test_archive_always_visible_and_update_uses_update_slot():
    handlers = (ROOT / 'app' / 'handlers.py').read_text()
    ui = (ROOT / 'app' / 'ui.py').read_text()
    assert 'archive_label = f"Архив · {archive_n}" if archive_n else "Архив"' in handlers
    assert 'button(emojis, "update", "Обновление", "settings:update")' in ui
    assert 'f"{e(self.emojis, \'update\')} <b>Обновление</b>"' in handlers
