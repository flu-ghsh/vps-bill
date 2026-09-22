from pathlib import Path


def test_server_open_callbacks_are_dedicated_and_legacy_supported():
    root = Path(__file__).parents[1]
    handlers = (root / "app" / "handlers.py").read_text()
    ui = (root / "app" / "ui.py").read_text()
    assert 'F.data.startswith("srvopen:")' in handlers
    assert 'F.data.startswith("server:")' in handlers  # legacy notification buttons
    assert 'f"srvopen:{server[\'id\']}"' in handlers
    assert '"Открыть сервер", f"srvopen:{server_id}"' in ui


def test_emoji_menu_is_paginated_and_has_update_slot():
    root = Path(__file__).parents[1]
    ui = (root / "app" / "ui.py").read_text()
    handlers = (root / "app" / "handlers.py").read_text()
    assert '"update": ("⬆️", "Обновление")' in ui
    assert 'page_size: int = 8' in ui
    assert 'emoji:page:' in ui
    assert 'F.data.startswith("emoji:page:")' in handlers
