from pathlib import Path

from app.db import Database


def test_archive_keeps_payment_history(tmp_path):
    db = Database(tmp_path / 'billing.db')
    sid = db.add_server(name='old-vps', provider='Host', amount_minor=500, currency='USD', next_due='2026-09-22', cycle='monthly')
    db.record_payment_only(sid, 500, 'USD', '2026-09-22', 'test')
    db.archive_server(sid)
    assert db.list_servers() == []
    assert db.archive_count() == 1
    assert db.recent_payments()[0]['server_id'] == sid
    db.restore_archived_server(sid)
    assert db.list_servers()[0]['id'] == sid


def test_v257_ui_and_scripts():
    root = Path(__file__).parents[1]
    ui = (root / 'app' / 'ui.py').read_text()
    handlers = (root / 'app' / 'handlers.py').read_text()
    update = (root / 'scripts' / 'update.sh').read_text()
    assert 'Что нового' not in ui
    assert 'В архив' in ui
    assert 'Удалить старые бекапы' in ui
    assert 'Обновление' in ui
    assert 'Автообновление' not in ui
    assert 'install-update-bridge.sh' in update
