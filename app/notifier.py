from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import __version__
from .billing import days_until, money, sum_by_currency
from .config import Settings
from .db import Database
from .monitoring import probe_host
from .ui import e, h, notification_buttons, update_offer_keyboard
from .updates import changelog_to_telegram_html, is_newer, latest_release, read_update_status


class Notifier:
    def __init__(self, bot: Bot, db: Database, settings: Settings):
        self.bot = bot
        self.db = db
        self.settings = settings
        self.tz = ZoneInfo(settings.timezone)
        self._stopping = asyncio.Event()
        self._last_monitor_run = 0.0
        self._monitor_parallel = 10
        self._last_update_attempt = 0.0

    async def stop(self):
        self._stopping.set()

    async def _broadcast(self, text: str, reply_markup=None) -> tuple[bool, str]:
        errors: list[str] = []
        for admin_id in self.settings.admin_ids:
            try:
                await self.bot.send_message(admin_id, text, reply_markup=reply_markup)
            except Exception as exc:
                msg = f"notify {admin_id} failed: {exc}"
                print(msg, flush=True)
                errors.append(msg)
        return not errors, "; ".join(errors)

    def _reminder_text(self, s: dict, d: int, *, snoozed: bool = False) -> str:
        emojis = self.db.get_emojis()
        if snoozed:
            head = f"{e(emojis, 'snooze')} <b>Напоминание об оплате</b>"
        elif d < 0:
            head = f"{e(emojis, 'status_overdue')} <b>ПРОСРОЧЕНА ОПЛАТА</b>"
        elif d == 0:
            head = f"{e(emojis, 'status_today')} <b>ОПЛАТА СЕГОДНЯ</b>"
        else:
            head = f"{e(emojis, 'money')} <b>СКОРО ОПЛАТА</b>"

        if d < 0:
            remain = f"Просрочено: <b>{abs(d)} дн.</b>"
        elif d == 0:
            remain = "Осталось: <b>сегодня</b>"
        elif d == 1:
            remain = "Осталось: <b>1 день</b>"
        else:
            remain = f"Осталось: <b>{d} дн.</b>"

        note = str(s.get("notes") or "").strip()
        note_line = f"{e(emojis, 'notes')} Заметка: {h(note)}\n" if note else ""

        return (
            f"{head}\n\n"
            f"{e(emojis, 'server')} <b>{h(s['name'])}</b>\n"
            f"{e(emojis, 'provider')} Хостер: {h(s['provider'] or '-')}\n"
            f"{note_line}\n"
            f"Сумма: <b>{money(s['amount_minor'], s['currency'])}</b>\n"
            f"{e(emojis, 'calendar')} Дата: <b>{date.fromisoformat(s['next_due']).strftime('%d.%m.%y')}</b>\n"
            f"{remain}"
        )

    def _outbox_markup(self, row: dict):
        kind = str(row.get("kind") or "")
        sid = int(row.get("server_id") or 0)
        emojis = self.db.get_emojis()
        if kind.startswith("reminder:") and sid:
            return notification_buttons(sid, emojis, due_date=row.get("due_date"))
        if kind == "balance" and sid:
            return InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💰 Пополнил баланс", callback_data=f"balance:topup:{sid}", style="success")
            ]])
        return None

    async def flush_outbox(self):
        for row in self.db.pending_outbox(limit=50):
            ok, error = await self._broadcast(row["text"], self._outbox_markup(row))
            if ok:
                self.db.mark_outbox_sent(row["id"])
                kind = str(row.get("kind") or "")
                if kind == "monthly":
                    self.db.mark_event(str(row["event_key"]))
                elif kind.startswith("reminder:") and row.get("server_id") and row.get("due_date"):
                    self.db.mark_notification(int(row["server_id"]), str(row["due_date"]), kind.removeprefix("reminder:"))
                elif kind == "balance" and row.get("server_id") and row.get("due_date"):
                    snapshot = str(row["due_date"])
                    self.db.mark_notification(int(row["server_id"]), snapshot, f"balance_low:{snapshot}")
            else:
                attempts = int(row.get("attempts") or 0) + 1
                # 1m, 2m, 4m... capped at 15m.
                retry = min(900, 60 * (2 ** min(4, attempts - 1)))
                self.db.mark_outbox_failed(row["id"], error or "send failed", retry)

    async def check_snoozes(self, now: datetime):
        for s in self.db.due_snoozes(now.isoformat()):
            d = days_until(s["next_due"], now.date())
            event_key = f"snooze:{s['id']}:{s['until_at']}"
            self.db.enqueue_outbox(
                event_key,
                "reminder:snooze",
                self._reminder_text(s, d, snoozed=True),
                server_id=s["id"],
                due_date=s["next_due"],
            )
            self.db.clear_snooze(s["id"])

    async def check_due(self, now: datetime):
        reminder_time = self.db.payment_reminder_time()
        hh, mm = (int(x) for x in reminder_time.split(":", 1))
        if (now.hour, now.minute) < (hh, mm):
            return
        today = now.date()
        reminder_days = set(self.db.get_reminder_days())
        overdue_daily = self.db.overdue_daily()
        for s in self.db.list_servers():
            if str(s.get("billing_mode") or "scheduled") == "balance":
                continue
            if self.db.is_snoozed(s["id"], now.isoformat()):
                continue
            d = days_until(s["next_due"], today)
            if d in reminder_days:
                kind = f"due:{d}"
            elif d < 0 and overdue_daily:
                kind = f"overdue:{today.isoformat()}"
            else:
                continue
            if self.db.notification_sent(s["id"], s["next_due"], kind):
                continue
            event_key = f"payment:{s['id']}:{s['next_due']}:{kind}"
            self.db.enqueue_outbox(
                event_key,
                f"reminder:{kind}",
                self._reminder_text(s, d),
                server_id=s["id"],
                due_date=s["next_due"],
            )

    async def check_balances(self, now: datetime):
        emojis = self.db.get_emojis()
        today = now.date()
        for s in self.db.list_servers():
            if str(s.get("billing_mode") or "scheduled") != "balance":
                continue
            daily = int(s.get("amount_minor") or 0)
            if daily <= 0:
                continue
            remaining = self.db.balance_remaining_minor(s, today)
            days_left = remaining // daily
            threshold = int(s.get("balance_alert_days") or 3)
            if days_left > threshold:
                continue
            snapshot = str(s.get("balance_updated_at") or today.isoformat())
            kind = f"balance_low:{snapshot}"
            if self.db.notification_sent(s["id"], snapshot, kind):
                continue
            text = (
                f"{e(emojis, 'warning')} <b>Заканчивается баланс</b>\n\n"
                f"{e(emojis, 'server')} <b>{h(s['name'])}</b>\n"
                f"Хостер: {h(s.get('provider') or '-')}\n\n"
                f"Остаток: <b>{money(remaining, s['currency'])}</b>\n"
                f"Расход: <b>{money(daily, s['currency'])}/день</b>\n"
                f"Хватит примерно на: <b>{days_left} дн.</b>"
            )
            event_key = f"balance:{s['id']}:{snapshot}"
            inserted = self.db.enqueue_outbox(event_key, "balance", text, server_id=s["id"], due_date=snapshot)
            if inserted:
                # notification_log is marked only after successful delivery by flush_outbox.
                pass

    async def monthly_report(self, now: datetime):
        if not self.db.monthly_report_enabled() or now.day != self.db.report_day():
            return
        if (now.hour, now.minute) < (self.db.report_hour(), self.db.report_minute()):
            return
        key = f"monthly:{now.year}-{now.month:02d}"
        if self.db.event_exists(key) or self.db.outbox_exists(key):
            return
        this_month = now.date().replace(day=1)
        prev_end = this_month
        prev_start = (this_month - timedelta(days=1)).replace(day=1)
        paid = self.db.payments_between(prev_start.isoformat(), prev_end.isoformat())
        totals = sum_by_currency(paid)
        emojis = self.db.get_emojis()
        lines = [f"{e(emojis, 'reports')} <b>Отчёт за {prev_start.strftime('%m.%Y')}</b>", "", f"Оплат: <b>{len(paid)}</b>"]
        for cur in ("RUB", "EUR", "USD"):
            if totals.get(cur):
                lines.append(f"• {money(totals[cur], cur)}")
        if not totals:
            lines.append("• 0")
        lines += ["", f"Активных серверов: <b>{len(self.db.list_servers())}</b>"]
        self.db.enqueue_outbox(key, "monthly", "\n".join(lines))

    def _update_check_target(self, now: datetime) -> datetime:
        hh, mm = (int(x) for x in self.db.payment_reminder_time().split(":", 1))
        reminder = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        target = reminder - timedelta(minutes=30)
        if target.date() < now.date():
            target += timedelta(days=1)
        return target

    async def check_update_result(self, now: datetime):
        status = read_update_status(self.settings.update_requests_dir)
        if not status or status.get("state") not in {"success", "error"}:
            return
        request_id = str(status.get("request_id") or "")
        if not request_id or self.db.update_result_notified() == request_id:
            return
        version = str(status.get("version") or "?")
        if status.get("state") == "success":
            text = (
                "✅ <b>VPS Bill обновлён</b>\n\n"
                f"Установлена версия: <b>{h(version)}</b>\n"
                "Backup, миграция и health-check завершены успешно."
            )
        else:
            error = str(status.get("error") or "неизвестная ошибка")
            text = (
                f"{e(self.db.get_emojis(), 'warning')} <b>Обновление не выполнено</b>\n\n"
                f"Версия: <b>{h(version)}</b>\n"
                f"Ошибка: <code>{h(error[:500])}</code>\n\n"
                "Текущая рабочая версия сохранена или восстановлена штатным rollback."
            )
        ok, _ = await self._broadcast(text)
        if ok:
            self.db.set_update_result_notified(request_id)

    async def check_updates(self, now: datetime):
        await self.check_update_result(now)
        if not self.db.update_check_enabled():
            return
        target = self._update_check_target(now)
        if now < target:
            return
        day_key = target.date().isoformat()
        if self.db.update_last_check_day() == day_key:
            return
        current_mono = time.monotonic()
        if current_mono - self._last_update_attempt < 1800:
            return
        self._last_update_attempt = current_mono
        try:
            rel = await latest_release()
        except Exception as exc:
            print(f"update check failed: {exc}", flush=True)
            return
        self.db.set_update_last_check_day(day_key)
        if not is_newer(rel.version, __version__):
            return
        if self.db.update_ignored_version() == rel.version:
            return
        remind_after = self.db.update_remind_after()
        if remind_after:
            try:
                if date.fromisoformat(remind_after) > now.date():
                    return
            except ValueError:
                pass
        elif self.db.update_last_offered() == rel.version:
            return
        notes = changelog_to_telegram_html(rel.notes, limit=2800)
        asset_note = "" if rel.asset_url else "\n\n⚠️ В релизе пока нет установочного архива."
        text = (
            "⬆️ <b>Доступна новая версия VPS Bill</b>\n\n"
            f"Установлена: <b>{h(__version__)}</b>\n"
            f"Доступна: <b>{h(rel.version)}</b>\n\n"
            "<b>Что изменилось:</b>\n"
            f"{notes}{asset_note}"
        )
        markup = update_offer_keyboard(rel.version) if rel.asset_url else None
        ok, _ = await self._broadcast(text, markup)
        if ok:
            self.db.set_update_last_offered(rel.version)
            self.db.set_update_remind_after("")

    async def _probe(self, s: dict) -> tuple[bool, dict[str, str]]:
        return await probe_host(
            str(s.get("ip") or "").strip(),
            method=self.db.monitor_method(),
            port=self.db.monitor_tcp_port(),
            timeout=self.db.monitor_timeout(),
        )


    def _probe_summary(self, details: dict[str, str]) -> str:
        method = details.get("method", "auto")
        port = details.get("port", str(self.db.monitor_tcp_port()))
        lines: list[str] = []

        if method in {"auto", "ping"}:
            ping_status = details.get("ping", "skip")
            ping_text = {
                "ok": "OK",
                "fail": "нет ответа",
                "skip": "не проверялся",
            }.get(ping_status, "неизвестно")
            lines.append(f"Ping: <b>{ping_text}</b>")

        if method in {"auto", "tcp"}:
            tcp_status = details.get("tcp", "skip")
            if tcp_status == "ok":
                tcp_text = "OK"
            elif tcp_status == "refused":
                tcp_text = "хост отвечает, порт закрыт"
            elif tcp_status == "skip" and details.get("ping") == "ok":
                tcp_text = "не проверялся (Ping OK)"
            elif tcp_status == "skip":
                tcp_text = "не проверялся"
            elif tcp_status == "timeout":
                tcp_text = "таймаут"
            elif tcp_status == "invalid":
                tcp_text = "некорректный IP"
            else:
                tcp_text = "нет соединения"
            lines.append(f"TCP {h(port)}: <b>{tcp_text}</b>")

        return "\n".join(lines)

    async def _check_one_server(self, s: dict, sem: asyncio.Semaphore):
        async with sem:
            ok, details = await self._probe(s)
        _, transition = self.db.update_monitor_result(s["id"], ok)
        if not transition:
            return
        emojis = self.db.get_emojis()
        probe_summary = self._probe_summary(details)
        if transition == "down":
            text = (
                f"{e(emojis, 'status_down')} <b>СЕРВЕР НЕДОСТУПЕН</b>\n\n"
                f"{e(emojis, 'server')} <b>{h(s['name'])}</b>\n"
                f"{e(emojis, 'ip')} <code>{h(s['ip'])}</code>\n"
                f"Хостер: {h(s.get('provider') or '-')}\n\n"
                f"Не отвечает после <b>{self.db.monitor_failures()} проверок подряд</b>.\n"
                f"{probe_summary}"
            )
        else:
            text = (
                f"{e(emojis, 'status_up')} <b>СЕРВЕР ВОССТАНОВЛЕН</b>\n\n"
                f"{e(emojis, 'server')} <b>{h(s['name'])}</b>\n"
                f"{e(emojis, 'ip')} <code>{h(s['ip'])}</code>\n"
                f"Хостер: {h(s.get('provider') or '-')}\n\n"
                "Сервер снова отвечает.\n"
                f"{probe_summary}"
            )
        state = self.db.monitor_state(s["id"])
        change = state.get("last_change") or datetime.now(self.tz).isoformat()
        event_key = f"monitor:{s['id']}:{transition}:{change}"
        self.db.enqueue_outbox(event_key, f"monitor:{transition}", text, server_id=s["id"])

    async def check_availability(self, now: datetime):
        if not self.db.monitoring_enabled():
            return
        current = time.monotonic()
        if current - self._last_monitor_run < self.db.monitor_interval():
            return
        self._last_monitor_run = current
        servers = self.db.monitored_servers()
        sem = asyncio.Semaphore(self._monitor_parallel)
        results = await asyncio.gather(*(self._check_one_server(s, sem) for s in servers), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                print(f"monitor worker failed: {result}", flush=True)

    async def _run_step(self, name: str, fn, now: datetime):
        try:
            await fn(now)
        except Exception as exc:
            print(f"notifier {name} error: {exc}", flush=True)

    async def run(self):
        while not self._stopping.is_set():
            now = datetime.now(self.tz)
            # Heartbeat is written every loop and checked by Docker healthcheck.
            self.db.set_runtime("notifier_heartbeat", now.isoformat(timespec="seconds"))
            try:
                await self.flush_outbox()
            except Exception as exc:
                print(f"notifier outbox error: {exc}", flush=True)
            for name, fn in (
                ("snoozes", self.check_snoozes),
                ("due", self.check_due),
                ("balances", self.check_balances),
                ("monthly", self.monthly_report),
                ("updates", self.check_updates),
                ("monitoring", self.check_availability),
            ):
                await self._run_step(name, fn, now)
            try:
                await self.flush_outbox()
            except Exception as exc:
                print(f"notifier outbox error: {exc}", flush=True)
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.settings.check_interval)
            except asyncio.TimeoutError:
                pass
