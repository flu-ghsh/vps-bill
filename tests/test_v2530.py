"""Regression tests for payment history navigation and isolated delete submenu.

Render the real payment handler via AST so tests can run without the Telegram SDK;
production aiogram integration continues to be exercised by the deployment.
"""
from __future__ import annotations

import ast
import asyncio
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.db import Database


class Button:
    def __init__(self, text, callback_data, **kwargs):
        self.text = text
        self.callback_data = callback_data
        self.kwargs = kwargs


def button(_emojis, slot, label, callback_data, **kwargs):
    return Button(label, callback_data, slot=slot, **kwargs)


class Message:
    def __init__(self):
        self.text = ""
        self.markup = None
        self.documents = []

    async def edit_text(self, text, *, reply_markup=None, **kwargs):
        self.text = text
        self.markup = reply_markup

    async def answer_document(self, document, *, caption=None, **kwargs):
        self.documents.append((document, caption))


class BufferedInputFile:
    def __init__(self, data, filename):
        self.data = data
        self.filename = filename


class Query:
    def __init__(self, data):
        self.data = data
        self.message = Message()
        self.answers = []

    async def answer(self, *args, **kwargs):
        self.answers.append((args, kwargs))


def load_handler_method(name):
    path = Path(__file__).parents[1] / "app/handlers.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BotHandlers")
    method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
    method = ast.AsyncFunctionDef(
        name=method.name, args=method.args, body=method.body, decorator_list=[],
        returns=method.returns, type_comment=None,
    )
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    scope = dict(
        CallbackQuery=Query,
        InlineKeyboardButton=Button, BufferedInputFile=BufferedInputFile,
        date=date, datetime=datetime, timedelta=timedelta,
        button=button,
        e=lambda _emojis, _slot: "💳",
        h=lambda value: escape(str(value)),
        money=lambda amount, currency: f"{amount / 100:.2f} {currency}",
        kb=lambda rows: SimpleNamespace(inline_keyboard=rows),
        back_main=lambda emojis: SimpleNamespace(inline_keyboard=[[button(emojis, "back", "Главное меню", "main")]]),
    )
    exec(compile(module, str(path), "exec"), scope)
    return scope[name]


def flatten_keyboard(query):
    assert query.message.markup is not None
    return [button for row in query.message.markup.inline_keyboard for button in row]


class PaymentNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(str(Path(self.tmp.name) / "billing.db"))
        with self.db.conn() as conn:
            conn.execute(
                "INSERT INTO servers (name,provider,amount_minor,currency,cycle,cycle_days,"
                "next_due,active,created_at,updated_at) VALUES "
                "('Demo','test',1000,'EUR','monthly',NULL,'2026-11-01',1,'2026-10-01','2026-10-01')"
            )
        self.handler = SimpleNamespace(db=self.db, today=date(2026, 10, 21), emojis={})
        self.handler.payments = load_handler_method("payments").__get__(self.handler)
        self.handler.payments_manage = load_handler_method("payments_manage").__get__(self.handler)

    def add_payment(self, stamp):
        with self.db.conn() as conn:
            conn.execute(
                "INSERT INTO payments (server_id,amount_minor,currency,due_date,paid_at,next_due,note) "
                "VALUES (1,1000,'EUR','2026-10-01',?,'2026-11-01','')", (stamp,)
            )

    def display(self, callback, *, manage=False):
        query = Query(callback)
        asyncio.run(self.handler.payments(query, manage=manage))
        return query

    def test_empty_history_no_deletion_list(self):
        self.assertIsNone(self.db.earliest_payment_month())
        q = self.display("payments")
        self.assertIn("В этом месяце оплат нет", q.message.text)
        self.assertEqual([b.callback_data for b in flatten_keyboard(q)], ["payments:manage:2026-10:0", "main"])

    def test_months_match_server_pagination_and_include_empty_months(self):
        self.add_payment("2026-08-16T10:00:00")
        self.add_payment("2026-10-21T08:00:00")
        self.assertEqual(self.db.earliest_payment_month(), date(2026, 8, 1))
        q = self.display("payments")
        buttons = flatten_keyboard(q)
        self.assertEqual([(b.text, b.callback_data) for b in buttons[:2]], [
            ("‹ 09.2026", "payments:month:2026-09:0"), ("10.2026 ›", "noop")
        ])
        self.assertEqual(len([b for b in buttons if b.kwargs.get("slot") == "delete"]), 1)
        self.assertEqual([b.text for b in buttons if b.kwargs.get("slot") == "delete"], ["Удаление платежей"])
        self.assertIn("История оплат", q.message.text)
        empty = self.display("payments:month:2026-09:0")
        self.assertIn("В этом месяце оплат нет.", empty.message.text)
        self.assertEqual([(b.text, b.callback_data) for b in flatten_keyboard(empty)[:2]], [
            ("‹ 08.2026", "payments:month:2026-08:0"),
            ("10.2026 ›", "payments:month:2026-10:0"),
        ])
        earliest = self.display("payments:month:2026-08:0")
        keys = flatten_keyboard(earliest)
        self.assertEqual([(b.text, b.callback_data) for b in keys[:2]], [
            ("‹ 08.2026", "noop"), ("09.2026 ›", "payments:month:2026-09:0")
        ])

    def test_delete_submenu_isolated_from_history(self):
        self.add_payment("2026-09-17T09:00:00")
        self.add_payment("2026-10-20T09:00:00")
        history = self.display("payments")
        self.assertEqual(len(flatten_keyboard(history)), 4)  # two month buttons, submenu, back
        self.assertTrue(all(not b.callback_data.startswith("payments:item:") for b in flatten_keyboard(history)))
        submenu = self.display("payments:manage:2026-10:0")
        self.assertIn("Удаление платежей", submenu.message.text)
        buttons = flatten_keyboard(submenu)
        self.assertEqual(len([b for b in buttons if b.callback_data.startswith("payments:item:")]), 1)
        self.assertIn("‹ 09.2026", [b.text for b in buttons])
        self.assertEqual(buttons[-1].callback_data, "payments:month:2026-10:0")
        september = self.display("payments:manage:2026-09:0")
        self.assertIn("10.2026 ›", [b.text for b in flatten_keyboard(september)])

    def test_all_month_payments_on_one_screen(self):
        self.add_payment("2026-09-10T09:00:00")
        for day in range(1, 18):
            self.add_payment(f"2026-10-{day:02d}T09:00:00")
        history = self.display("payments")
        buttons = flatten_keyboard(history)
        self.assertEqual(history.message.text.count("• "), 17)
        self.assertIn("Записей: 17", history.message.text)
        self.assertNotIn("Стр.", str([b.text for b in buttons]))
        self.assertEqual(len(buttons), 4)  # one month-navigation row and actions
        # Old saved callbacks still work, but history always shows the whole month.
        page2 = self.display("payments:month:2026-10:1")
        self.assertEqual(page2.message.text.count("• "), 17)
        managed = self.display("payments:manage:2026-10:0")
        self.assertEqual(len([b for b in flatten_keyboard(managed) if b.callback_data.startswith("payments:item:")]), 17)
        self.assertNotIn("Стр.", str([b.text for b in flatten_keyboard(managed)]))
        old = self.display("payments:month:2026-01:0")
        self.assertIn("Сентябрь", old.message.text)  # clamp to earliest available

    def test_long_month_export_contains_every_payment(self):
        for n in range(160):
            self.add_payment(f"2026-10-{n % 28 + 1:02d}T09:{n % 60:02d}:00")
        history = self.display("payments")
        self.assertEqual(len(history.message.documents), 1)
        file, caption = history.message.documents[0]
        self.assertEqual(file.filename, "payments-2026-10.txt")
        self.assertIn("Записей: 160", file.data.decode())
        self.assertEqual(file.data.decode().count(" | Demo | "), 160)
        self.assertEqual(len(flatten_keyboard(history)), 2)  # submenu and back, same-month history
        self.assertIn("одним файлом", history.message.text)

    def test_large_delete_submenu_still_reaches_oldest_payments(self):
        for n in range(85):
            self.add_payment(f"2026-10-{n % 28 + 1:02d}T09:{n % 60:02d}:00")
        first = self.display("payments:manage:2026-10:0")
        buttons = flatten_keyboard(first)
        self.assertEqual(len([b for b in buttons if b.callback_data.startswith("payments:item:")]), 80)
        self.assertIn("Ещё платежи", [b.text for b in buttons])
        second = self.display("payments:manage:2026-10:1")
        more = flatten_keyboard(second)
        self.assertEqual(len([b for b in more if b.callback_data.startswith("payments:item:")]), 5)
        self.assertIn("Предыдущие платежи", [b.text for b in more])
        self.assertFalse(any("Стр." in b.text for b in buttons + more))

    def test_rollover_across_year(self):
        self.add_payment("2025-12-02T01:00:00")
        q = self.display("payments:month:2026-01:0")
        self.assertIn("Январь 2026", q.message.text)
        self.assertIn("‹ 12.2025", [b.text for b in flatten_keyboard(q)])
        self.assertIn("02.2026 ›", [b.text for b in flatten_keyboard(q)])
        self.assertIn("payments:month:2025-12:0", [b.callback_data for b in flatten_keyboard(q)])

    def test_changelog_without_dates_and_preserving_history(self):
        changelog = (Path(__file__).parents[1] / "CHANGELOG.md").read_text()
        self.assertTrue(changelog.startswith("# Changelog\n\n## 2.5.31\n"))
        self.assertTrue(changelog.index("## 2.5.31") < changelog.index("## 2.5.30") < changelog.index("## 2.5.29") < changelog.index("## 2.5.28"))
        self.assertNotIn("## 2.5.31 —", changelog)


if __name__ == "__main__":
    unittest.main()
