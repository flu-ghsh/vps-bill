"""Tariff changes: price and period may change together without rewriting payments.

Handler tests run the real method bodies with small Telegram stubs, so no aiogram
installation is required to check the state transitions and UI callbacks.
"""
from __future__ import annotations

import ast
import asyncio
import re
import unittest
from datetime import date
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.billing import cycle_label, money, parse_amount_minor
from app.db import Database

ROOT = Path(__file__).parents[1]


def load_handlers(*names):
    tree = ast.parse((ROOT / 'app/handlers.py').read_text())
    klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'BotHandlers')
    methods = [n for n in klass.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
    assert len(methods) == len(names)
    for method in methods:
        method.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[]))
    scope = dict(
        EditTariff=SimpleNamespace(amount='state:amount', confirm='state:confirm'),
        CallbackQuery=object, FSMContext=object, Message=object,
        e=lambda _emojis, slot: slot,
        h=lambda val: escape(str(val)),
        money=money, cycle_label=cycle_label, parse_amount_minor=parse_amount_minor,
        server_card=lambda srv, emoji: f"server {srv['name']}: {srv['amount_minor']} / {srv['cycle']}",
        server_buttons=lambda *args, **kwargs: ('server-buttons', args, kwargs),
        back_main=lambda emojis: ('back-main',),
        main_menu=lambda emojis: ('main',),
        kb=lambda rows: rows,
        button=lambda emojis, slot, label, callback, **kwargs: (label, callback, kwargs),
        tariff_cycle_keyboard=lambda *args, **kwargs: ('cycles', args, kwargs),
        re=re,
    )
    exec(compile(module, str(ROOT / 'app/handlers.py'), 'exec'), scope)
    return scope


class State:
    def __init__(self):
        self.data = {}
        self.name = None
    async def clear(self):
        self.name = None
        self.data.clear()
    async def set_state(self, name):
        self.name = name
    async def update_data(self, **kwargs):
        self.data.update(kwargs)
    async def get_data(self):
        return dict(self.data)


class Msg:
    def __init__(self, text=''):
        self.text = text
        self.output = ''
        self.reply_markup = None
    async def edit_text(self, text, *, reply_markup=None, **kwargs):
        self.output = text
        self.reply_markup = reply_markup
    async def answer(self, text, *, reply_markup=None, **kwargs):
        self.output = text
        self.reply_markup = reply_markup


class Query:
    def __init__(self, data):
        self.data = data
        self.message = Msg()
        self.answered = []
    async def answer(self, *args, **kwargs):
        self.answered.append((args, kwargs))


class TariffTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Database(str(Path(tmp.name) / 'billing.db'))
        with self.db.conn() as conn:
            conn.execute('''INSERT INTO servers
                (name, provider, amount_minor, currency, next_due, cycle, billing_mode, created_at, updated_at)
                VALUES ('Test VPS','Example',300,'EUR','2026-11-01','weekly','scheduled','2026-10-01','2026-10-01')''')
            self.sid = conn.execute('SELECT id FROM servers').fetchone()[0]
            conn.execute('''INSERT INTO payments
                (server_id, amount_minor, currency, due_date, paid_at, next_due, note)
                VALUES (?,300,'EUR','2026-10-01','2026-10-01T10:00:00','2026-10-08','old rate')''', (self.sid,))
        self.state = State()
        self.handler = SimpleNamespace(
            db=self.db, emojis={}, today=date(2026, 10, 31),
        )
        functions = load_handlers('tariff_open', 'tariff_select_cycle', 'tariff_amount_input',
                                  'tariff_confirm', 'tariff_cancel')
        for name, f in functions.items():
            if name.startswith('tariff_'):
                setattr(self.handler, name, f.__get__(self.handler))

    def test_weekly_to_monthly_and_price(self):
        old_due = self.db.get_server(self.sid)['next_due']
        q1 = Query(f'tariff:open:{self.sid}')
        asyncio.run(self.handler.tariff_open(q1, self.state))
        self.assertIn('Стоимость и период', q1.message.output)
        self.assertEqual(q1.message.reply_markup[0], 'cycles')
        q2 = Query(f'tariff:cycle:{self.sid}:monthly')
        asyncio.run(self.handler.tariff_select_cycle(q2, self.state))
        self.assertEqual(self.state.name, 'state:amount')
        m = Msg('10.50')
        asyncio.run(self.handler.tariff_amount_input(m, self.state))
        self.assertEqual(self.state.name, 'state:confirm')
        self.assertIn('10.50', m.output)
        q3 = Query(f'tariff:save:{self.sid}')
        asyncio.run(self.handler.tariff_confirm(q3, self.state))
        s = self.db.get_server(self.sid)
        self.assertEqual(s['cycle'], 'monthly')
        self.assertEqual(s['amount_minor'], 1050)
        self.assertEqual(s['next_due'], old_due)
        self.assertIsNone(s['cycle_days'])
        self.assertIsNone(self.state.name)
        with self.db.conn() as conn:
            payment = conn.execute('SELECT amount_minor, due_date, next_due FROM payments').fetchone()
        self.assertEqual(tuple(payment), (300, '2026-10-01', '2026-10-08'))

    def test_price_only_and_stale_update(self):
        self.assertTrue(self.db.update_server_tariff(
            self.sid, amount_minor=500, cycle='weekly', expected_amount_minor=300,
            expected_cycle='weekly', expected_cycle_days=None,
        ))
        self.assertFalse(self.db.update_server_tariff(
            self.sid, amount_minor=1000, cycle='monthly', expected_amount_minor=300,
            expected_cycle='weekly', expected_cycle_days=None,
        ))
        self.assertEqual(self.db.get_server(self.sid)['amount_minor'], 500)
        self.assertEqual(self.db.get_server(self.sid)['cycle'], 'weekly')

    def test_cancel_does_not_write(self):
        q = Query(f'tariff:cycle:{self.sid}:monthly')
        asyncio.run(self.handler.tariff_select_cycle(q, self.state))
        canceled = Query(f'tariff:cancel:{self.sid}')
        asyncio.run(self.handler.tariff_cancel(canceled, self.state))
        self.assertEqual(self.db.get_server(self.sid)['cycle'], 'weekly')
        self.assertEqual(self.db.get_server(self.sid)['amount_minor'], 300)
        self.assertEqual(self.state.data, {})

    def test_balance_mode_cannot_change_tariff(self):
        with self.db.conn() as conn:
            conn.execute("UPDATE servers SET billing_mode='balance' WHERE id=?", (self.sid,))
        q = Query(f'tariff:open:{self.sid}')
        asyncio.run(self.handler.tariff_open(q, self.state))
        self.assertTrue(q.answered[-1][1]['show_alert'])
        self.assertFalse(self.db.update_server_tariff(
            self.sid, amount_minor=400, cycle='monthly', expected_amount_minor=300,
            expected_cycle='weekly', expected_cycle_days=None,
        ))
        self.assertEqual(self.db.get_server(self.sid)['amount_minor'], 300)

    def test_changelog_format_and_past_content(self):
        text = (ROOT / 'CHANGELOG.md').read_text()
        self.assertTrue(text.startswith('# Changelog\n\n## 2.5.36\n\n'))
        old = re.findall(r'^## (\d+\.\d+\.\d+)$', text, flags=re.M)
        self.assertEqual(old[:5], ['2.5.36', '2.5.35', '2.5.34', '2.5.33', '2.5.32'])
        self.assertNotIn('## 2.5.32 —', text)


if __name__ == '__main__':
    unittest.main()
