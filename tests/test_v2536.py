"""Manual balance reconciliation in daily prepaid mode."""
from datetime import date, timedelta
from pathlib import Path

import pytest
from app.db import Database


def test_adjust_balance_replaces_amount_without_payment(tmp_path):
    db = Database(tmp_path/'test.db')
    sid = db.add_server(name='Daily',provider='H',amount_minor=34,currency='USD',next_due='2026-12-30',cycle='daily',billing_mode='balance',balance_minor=1000)
    with db.conn() as c:
        c.execute('UPDATE servers SET balance_updated_at=? WHERE id=?',((date.today()-timedelta(days=2)).isoformat(),sid))
    before = db.get_server(sid)
    assert db.balance_remaining_minor(before) == 932
    payments_before = db.payments_between('2000-01-01','2100-01-01')
    assert db.set_balance_remaining(sid,540)
    after = db.get_server(sid)
    assert after['balance_minor']==540
    assert db.balance_remaining_minor(after)==540
    assert after['next_due']==(date.today()+timedelta(days=540//34)).isoformat()
    assert db.payments_between('2000-01-01','2100-01-01')==payments_before
    assert db.set_balance_remaining(sid,0)
    assert db.balance_remaining_minor(db.get_server(sid)) == 0
    assert db.get_server(sid)['next_due']==date.today().isoformat()
    assert db.set_balance_remaining(sid,100)
    assert db.balance_remaining_minor(db.get_server(sid)) == 100


def test_adjust_balance_rejects_invalid_and_other_modes(tmp_path):
    db=Database(tmp_path/'test.db')
    sid=db.add_server(name='Monthly',provider='H',amount_minor=100,currency='RUB',next_due='2026-12-01',cycle='monthly')
    assert db.set_balance_remaining(sid,100) is False
    for invalid in (-1,10**15+1,'100',True):
        with pytest.raises(ValueError):
            db.set_balance_remaining(sid,invalid)


def test_adjust_button_and_premium_slot():
    ui=Path('app/ui.py').read_text()
    handlers=Path('app/handlers.py').read_text()
    assert '"Изменить баланс"' in ui
    assert 'F.data.startswith("balance:adjust:")' in handlers
    assert 'BalanceAdjustment.confirm' in handlers
    assert "e(self.emojis, 'money')" in handlers
    assert "e(self.emojis, 'success')" in handlers
