from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot

from .billing import days_until, money, sum_by_currency
from .config import Settings
from .db import Database
from .ui import h, notification_buttons


class Notifier:
    def __init__(self, bot: Bot, db: Database, settings: Settings):
        self.bot = bot
        self.db = db
        self.settings = settings
        self.tz = ZoneInfo(settings.timezone)
        self._stopping = asyncio.Event()

    async def stop(self):
        self._stopping.set()

    async def _broadcast(self, text: str, reply_markup=None):
        for admin_id in self.settings.admin_ids:
            try:
                await self.bot.send_message(admin_id, text, reply_markup=reply_markup)
            except Exception:
                pass

    def _reminder_text(self, s: dict, d: int, snoozed: bool = False) -> str:
        if snoozed:
            head = "⏰ <b>Напоминание об оплате</b>"
        elif d < 0:
            head = "🔴 <b>ПРОСРОЧЕНА ОПЛАТА</b>"
        elif d == 0:
            head = "🟠 <b>ОПЛАТА СЕГОДНЯ</b>"
        else:
            head = "💸 <b>СКОРО ОПЛАТА</b>"
        if d < 0:
            remain = f"Просрочено: <b>{abs(d)} дн.</b>"
        elif d == 0:
            remain = "Осталось: <b>сегодня</b>"
        elif d == 1:
            remain = "Осталось: <b>1 день</b>"
        else:
            remain = f"Осталось: <b>{d} дн.</b>"
        return (
            f"{head}\n\n"
            f"🖥 <b>{h(s['name'])}</b>\n"
            f"Провайдер: {h(s['provider'] or '—')}\n\n"
            f"Сумма: <b>{money(s['amount_minor'], s['currency'])}</b>\n"
            f"Дата: <b>{date.fromisoformat(s['next_due']).strftime('%d.%m.%Y')}</b>\n"
            f"{remain}"
        )

    async def check_snoozes(self, now: datetime):
        for s in self.db.due_snoozes(now.isoformat()):
            d = days_until(s["next_due"], now.date())
            await self._broadcast(self._reminder_text(s, d, snoozed=True), notification_buttons(s["id"]))
            self.db.clear_snooze(s["id"])

    async def check_due(self, now: datetime):
        today = now.date()
        for s in self.db.list_servers():
            if self.db.is_snoozed(s["id"], now.isoformat()):
                continue
            d = days_until(s["next_due"], today)
            if d in self.settings.reminder_days:
                kind = f"due:{d}"
            elif d < 0:
                kind = f"overdue:{today.isoformat()}"
            else:
                continue
            if self.db.notification_sent(s["id"], s["next_due"], kind):
                continue
            await self._broadcast(self._reminder_text(s, d), notification_buttons(s["id"]))
            self.db.mark_notification(s["id"], s["next_due"], kind)

    async def monthly_report(self, now: datetime):
        if not self.settings.monthly_report_enabled or now.day != 1 or now.hour < self.settings.report_hour:
            return
        key = f"monthly:{now.year}-{now.month:02d}"
        if self.db.event_exists(key):
            return
        this_month = now.date().replace(day=1)
        prev_end = this_month
        prev_start = (this_month - timedelta(days=1)).replace(day=1)
        paid = self.db.payments_between(prev_start.isoformat(), prev_end.isoformat())
        totals = sum_by_currency(paid)
        lines = [f"📊 <b>Отчёт за {prev_start.strftime('%m.%Y')}</b>", "", f"Оплат: <b>{len(paid)}</b>"]
        for cur, total in totals.items():
            lines.append(f"• {money(total, cur)}")
        if not totals:
            lines.append("• 0")
        lines += ["", f"Активных серверов: <b>{len(self.db.list_servers())}</b>"]
        await self._broadcast("\n".join(lines))
        self.db.mark_event(key)

    async def run(self):
        while not self._stopping.is_set():
            now = datetime.now(self.tz)
            try:
                await self.check_snoozes(now)
                await self.check_due(now)
                await self.monthly_report(now)
            except Exception as exc:
                print(f"notifier error: {exc}", flush=True)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.settings.check_interval)
            except asyncio.TimeoutError:
                pass
