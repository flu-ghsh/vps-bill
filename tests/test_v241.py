from datetime import date
from app.db import Database


def _db(tmp_path):
    db=Database(tmp_path/'billing.db')
    db.migrate()
    return db


def test_down_monitored_servers(tmp_path):
    db=_db(tmp_path)
    sid=db.add_server(name='down-one', provider='p', amount_minor=100, currency='RUB', next_due=date.today().isoformat(), cycle='monthly')
    db.update_server_field(sid, 'ip', '1.1.1.1')
    db.toggle_server_monitoring(sid)
    for _ in range(db.monitor_failures()):
        db.update_monitor_result(sid, False)
    rows=db.down_monitored_servers()
    assert [x['id'] for x in rows] == [sid]


def test_card_source_renders_note_on_separate_line():
    # Regression guard without importing aiogram in the lightweight test env.
    src=open('app/ui.py', encoding='utf-8').read()
    assert "lines.append(f\"{e(emojis, 'notes')} {h(server['notes'])}\")" in src
    assert 'lines.append("   ".join(meta_parts))' not in src
