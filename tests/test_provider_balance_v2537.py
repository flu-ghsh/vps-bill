from datetime import date, timedelta
from app.db import Database


def add(db, name, host='Cloud', currency='USD', rate=100, balance=0):
    return db.add_server(name=name, provider=host, currency=currency, amount_minor=rate,
                         next_due=date.today().isoformat(), cycle='daily', billing_mode='balance', balance_minor=balance)


def test_shared_balance_and_topup(tmp_path):
    db=Database(tmp_path/'db.sqlite')
    a=add(db,'A',balance=1000)
    b=add(db,'B',rate=200,balance=9000)
    assert db.balance_remaining_minor(db.get_server(a)) == 1000
    assert db.balance_remaining_minor(db.get_server(b)) == 1000
    with db.conn() as c:
        c.execute('UPDATE provider_balances SET balance_updated_at=?',((date.today()-timedelta(days=2)).isoformat(),))
    assert db.balance_remaining_minor(db.get_server(a)) == 400
    assert db.provider_balance('Cloud','USD')['daily_minor'] == 300
    assert db.topup_balance(b,500) == 900
    assert db.balance_remaining_minor(db.get_server(a)) == 900
    assert len(db.payments_between('2000-01-01','2100-01-01')) == 1
    assert db.get_server(a)['next_due'] == db.get_server(b)['next_due']
    assert db.set_balance_remaining(a,1400)
    assert db.balance_remaining_minor(db.get_server(b)) == 1400
    assert len(db.payments_between('2000-01-01','2100-01-01')) == 1


def test_settles_before_new_server_and_rate_change(tmp_path):
    db=Database(tmp_path/'db.sqlite')
    a=add(db,'A',balance=1000)
    with db.conn() as c:
        c.execute('UPDATE provider_balances SET balance_updated_at=?',((date.today()-timedelta(days=2)).isoformat(),))
    b=add(db,'B',rate=200)
    assert db.balance_remaining_minor(db.get_server(b)) == 800
    assert db.update_balance_daily_rate(a,100,150)
    assert db.balance_remaining_minor(db.get_server(b)) == 800
    assert db.provider_daily_cost('Cloud','USD') == 350


def test_migration_and_currency_separation(tmp_path):
    db=Database(tmp_path/'db.sqlite')
    a=add(db,'A',balance=1000)
    b=add(db,'B',rate=50)
    eur=add(db,'EUR',currency='EUR',balance=2500)
    with db.conn() as c:
        c.execute('DELETE FROM provider_balances')
        c.execute("DELETE FROM meta WHERE key='provider_balance_migrated'")
        c.execute('UPDATE servers SET balance_minor=1000 WHERE id=?',(a,))
        c.execute('UPDATE servers SET balance_minor=500 WHERE id=?',(b,))
    db=Database(tmp_path/'db.sqlite')
    assert db.balance_remaining_minor(db.get_server(a)) == 1500
    assert db.balance_remaining_minor(db.get_server(eur)) == 2500
    db=Database(tmp_path/'db.sqlite')
    assert db.balance_remaining_minor(db.get_server(a)) == 1500


def test_rename_merges_balances_without_double_charging(tmp_path):
    db=Database(tmp_path/'db.sqlite')
    a=add(db,'A',host='Old',balance=1000)
    b=add(db,'B',host='New',rate=200,balance=2000)
    with db.conn() as c:
        c.execute('UPDATE provider_balances SET balance_updated_at=?',((date.today()-timedelta(days=1)).isoformat(),))
    assert db.rename_provider('Old','New') == 1
    assert db.provider_daily_cost('New','USD')==300
    assert db.balance_remaining_minor(db.get_server(a)) == 2700
    assert db.balance_remaining_minor(db.get_server(b)) == 2700
    assert db.provider_balance('Old','USD') is None
