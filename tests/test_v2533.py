"""Daily tariff settlement, monthly accounting and manual monitor wiring."""
from datetime import date, timedelta
from pathlib import Path
import ast

from app.db import Database
from app.billing import sum_by_currency


def test_daily_balance_tariff_preserves_remaining(tmp_path):
    db = Database(tmp_path / 'test.db')
    sid = db.add_server(name='Example', provider='ExampleHost', amount_minor=100,
                        currency='EUR', next_due='2026-12-30', cycle='daily',
                        billing_mode='balance', balance_minor=2000)
    with db.conn() as c:
        c.execute('UPDATE servers SET balance_updated_at=?,balance_minor=? WHERE id=?',
                  ((date.today()-timedelta(days=2)).isoformat(),2000,sid))
    assert db.update_balance_daily_rate(sid,100,200)
    s = db.get_server(sid)
    assert s['balance_minor']==1800
    assert s['amount_minor']==200
    assert not db.update_balance_daily_rate(sid,100,300)
    assert db.balance_remaining_minor(s)==1800


def test_month_end_posts_once_preserves_cash_totals(tmp_path):
    db = Database(tmp_path / 'test.db')
    sid = db.add_server(name='Test VPS', provider='Provider', amount_minor=250,
                        currency='RUB', next_due='2026-12-30', cycle='daily',
                        billing_mode='balance', balance_minor=10000)
    with db.conn() as c:
        c.execute('UPDATE daily_rate_history SET effective_day=? WHERE server_id=?',('2026-11-01',sid))
        c.execute('UPDATE servers SET created_at=? WHERE id=?',('2026-11-01',sid))
    assert db.record_daily_monthly_expenses(date(2026,11,29)) == 0
    assert db.record_daily_monthly_expenses(date(2026,11,30)) == 1
    assert db.record_daily_monthly_expenses(date(2026,11,30)) == 0
    rows=db.payments_between('2026-11-01','2026-12-01')
    assert len(rows)==1 and rows[0]['amount_minor']==7500
    assert rows[0]['paid_at'].startswith('2026-11-30')
    assert not sum_by_currency(rows)


def test_manual_monitor_has_button_handler_and_ping():
    ui=Path('app/ui.py').read_text()
    handlers=Path('app/handlers.py').read_text()
    assert 'callback_data="monitor:checknow"' not in ui or 'monitor:checknow' in ui
    assert '"monitor:checknow"' in ui and 'F.data == "monitor:checknow"' in handlers
    assert 'ping_probe(ip, timeout, attempts=1)' in handlers
    assert 'await q.message.answer(message)' in handlers
    tree=ast.parse(handlers)
    cls=next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name=='BotHandlers')
    assert any(isinstance(n,ast.AsyncFunctionDef) and n.name=='monitor_check_now' for n in cls.body)
