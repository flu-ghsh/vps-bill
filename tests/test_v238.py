from datetime import date, timedelta
from pathlib import Path

from app.db import Database


def test_balance_mode_and_topup(tmp_path: Path):
    db = Database(tmp_path / 'billing.db')
    sid = db.add_server(
        name='daily', provider='hoster', amount_minor=10000, currency='RUB',
        next_due=(date.today()+timedelta(days=10)).isoformat(), cycle='daily',
        billing_mode='balance', balance_minor=100000, balance_alert_days=3,
    )
    s = db.get_server(sid)
    assert s['billing_mode'] == 'balance'
    assert db.balance_remaining_minor(s, date.today()) == 100000
    new = db.topup_balance(sid, 50000)
    assert new == 150000
    assert db.recent_payments(1)[0]['note'] == 'Пополнение баланса'


def test_tag_toggle(tmp_path: Path):
    db = Database(tmp_path / 'billing.db')
    a = db.add_server(name='a', provider='p', amount_minor=1, currency='RUB', next_due=date.today().isoformat(), cycle='monthly')
    b = db.add_server(name='b', provider='p', amount_minor=1, currency='RUB', next_due=date.today().isoformat(), cycle='monthly')
    db.add_server_tag(a, 'vpn')
    db.add_server_tag(b, 'vpn')
    db.add_server_tag(b, 'prod')
    assert db.used_tags()[0] == 'vpn'
    assert db.toggle_server_tag(a, 'prod') is True
    assert db.toggle_server_tag(a, 'prod') is False
