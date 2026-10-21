from __future__ import annotations

import ast
import re
import sqlite3
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.billing import next_due, monthly_equivalent_minor
from app.db import Database


class Version2529Tests(unittest.TestCase):
    def test_30_and_31_days_are_fixed_lengths(self):
        self.assertEqual(next_due("2026-01-31", "days30"), "2026-03-02")
        self.assertEqual(next_due("2026-01-31", "days31"), "2026-03-03")
        self.assertEqual(next_due("2026-01-31", "monthly"), "2026-02-28")
        self.assertGreater(monthly_equivalent_minor(10000, "days30"), 0)
        self.assertGreater(monthly_equivalent_minor(10000, "days31"), 0)

    def test_delete_payment_does_not_touch_server(self):
        with TemporaryDirectory() as folder:
            db = Database(str(Path(folder) / "billing.db"))
            with db.conn() as conn:
                conn.execute(
                    "INSERT INTO servers (name,provider,amount_minor,currency,cycle,cycle_days,"
                    "next_due,active,created_at,updated_at) "
                    "VALUES ('unit-test','test',1000,'EUR','monthly',NULL,'2026-12-01',1,"
                    "'2026-10-01','2026-10-01')"
                )
                server_id = conn.execute("SELECT id FROM servers WHERE name='unit-test'").fetchone()[0]
                conn.execute(
                    "INSERT INTO payments (server_id,amount_minor,currency,due_date,paid_at,next_due,note) "
                    "VALUES (?,1000,'EUR','2026-10-01','2026-10-01T12:00:00','2026-11-01','')",
                    (server_id,),
                )
                payment_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            self.assertIsNotNone(db.get_payment(payment_id))
            self.assertTrue(db.delete_payment(payment_id))
            self.assertFalse(db.delete_payment(payment_id))
            self.assertIsNone(db.get_payment(payment_id))
            with db.conn() as conn:
                row = conn.execute("SELECT next_due FROM servers WHERE id=?",(server_id,)).fetchone()
            self.assertEqual(row[0], "2026-12-01")

    def test_changelog_version_order(self):
        text = (Path(__file__).parents[1] / "CHANGELOG.md").read_text()
        versions = re.findall(r"(?m)^## (\d+\.\d+\.\d+)$", text)
        old_start = versions.index("2.5.29")
        self.assertEqual(versions[old_start:old_start + 4], ["2.5.29", "2.5.28", "2.5.27", "2.5.26"])
        self.assertEqual(versions, sorted(versions, key=lambda v: tuple(map(int, v.split('.'))), reverse=True))


if __name__ == '__main__':
    unittest.main()
