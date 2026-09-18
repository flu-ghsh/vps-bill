from pathlib import Path
from app.db import Database


def test_dictionary_renames(tmp_path: Path):
    db = Database(tmp_path / 'billing.db')
    db.migrate()
    a = db.add_server(name='a', provider='Hetzner', amount_minor=100, currency='EUR', next_due='2026-10-01', cycle='monthly')
    b = db.add_server(name='b', provider='Hetzner', amount_minor=200, currency='EUR', next_due='2026-10-01', cycle='monthly')
    db.update_server_field(a, 'country', 'Finland')
    db.update_server_field(b, 'country', 'Finland')
    db.update_server_field(a, 'tags', 'vpn,prod')
    db.update_server_field(b, 'tags', 'vpn,test')

    assert db.rename_provider('Hetzner', 'Hetzner Cloud') == 2
    assert db.rename_country('Finland', 'Финляндия') == 2
    assert db.rename_tag('vpn', 'proxy') == 2

    sa = db.get_server(a)
    sb = db.get_server(b)
    assert sa['provider'] == 'Hetzner Cloud' and sb['provider'] == 'Hetzner Cloud'
    assert sa['country'] == 'Финляндия' and sb['country'] == 'Финляндия'
    assert sa['tags'] == 'proxy,prod'
    assert sb['tags'] == 'proxy,test'


def test_tag_rename_deduplicates(tmp_path: Path):
    db = Database(tmp_path / 'billing.db')
    db.migrate()
    sid = db.add_server(name='a', provider='X', amount_minor=100, currency='RUB', next_due='2026-10-01', cycle='monthly')
    db.update_server_field(sid, 'tags', 'vpn,proxy')
    assert db.rename_tag('vpn', 'proxy') == 1
    assert db.get_server(sid)['tags'] == 'proxy'
