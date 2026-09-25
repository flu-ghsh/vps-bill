from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import MessageEntityType
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import __version__
from .backup_archive import create_backup_archive, delete_old_backup_files
from .billing import annual_equivalent_minor, money, monthly_equivalent_minor, next_due, parse_amount_minor, sum_by_currency
from .config import Settings
from .db import Database
from .updates import changelog_to_telegram_html, create_update_request, is_newer, latest_release
from .ui import (
    EMOJI_SLOTS,
    back_main,
    billing_cycles_keyboard,
    button,
    calendar_keyboard,
    cancel_keyboard,
    currency_keyboard,
    currencies_settings_keyboard,
    country_picker_keyboard,
    tag_picker_keyboard,
    dictionaries_keyboard,
    dictionary_items_keyboard,
    dictionary_edit_keyboard,
    dictionary_delete_confirm_keyboard,
    demo_confirm_keyboard,
    daily_mode_keyboard,
    balance_alert_keyboard,
    cycle_keyboard,
    e,
    emoji_edit_keyboard,
    emoji_keyboard,
    h,
    main_menu,
    monitoring_settings_keyboard,
    notification_buttons,
    pagination_row,
    provider_keyboard,
    reminder_keyboard,
    reports_keyboard,
    server_buttons,
    server_card,
    server_details_keyboard,
    server_edit_back_keyboard,
    trash_item_keyboard,
    trash_list_keyboard,
    archive_list_keyboard,
    archive_item_keyboard,
    backups_keyboard,
    settings_keyboard,
    update_confirm_keyboard,
    update_settings_keyboard,
)


class AddServer(StatesGroup):
    name = State()
    provider = State()
    cycle = State()
    daily_mode = State()
    currency = State()
    amount = State()
    balance = State()
    balance_alert = State()
    due = State()
    record_current = State()


class ChangeDate(StatesGroup):
    due = State()


class EmojiEdit(StatesGroup):
    waiting = State()


class CurrencyAdd(StatesGroup):
    waiting = State()


class EditServerField(StatesGroup):
    waiting = State()


class BalanceTopup(StatesGroup):
    waiting = State()


class DictionaryRename(StatesGroup):
    waiting = State()


class MonitorTcpPort(StatesGroup):
    waiting = State()


class ReminderTimeInput(StatesGroup):
    waiting = State()


class ReportDayInput(StatesGroup):
    waiting = State()


class ReportTimeInput(StatesGroup):
    waiting = State()


class ReportScheduleInput(StatesGroup):
    waiting = State()


class ProviderUrlInput(StatesGroup):
    waiting = State()


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def compact_money(amount_minor: int, currency: str) -> str:
    value = f"{int(amount_minor) / 100:.2f}".rstrip("0").rstrip(".")
    symbols = {"RUB": "₽", "USD": "$", "EUR": "€"}
    code = str(currency or "").upper()
    return f"{value}{symbols.get(code, code)}"


def day_word(value: int) -> str:
    n = abs(int(value))
    if 11 <= n % 100 <= 14:
        return "дней"
    if n % 10 == 1:
        return "день"
    if n % 10 in (2, 3, 4):
        return "дня"
    return "дней"


def relative_due(days: int) -> str:
    if days < 0:
        n = abs(days)
        return f"просрочено на {n} {day_word(n)}"
    if days == 0:
        return "сегодня"
    if days == 1:
        return "завтра"
    return f"через {days} {day_word(days)}"


class BotHandlers:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.router = Router()
        self._register()

    @property
    def today(self) -> date:
        return datetime.now(ZoneInfo(self.settings.timezone)).date()

    @property
    def emojis(self) -> dict[str, str]:
        return self.db.get_emojis()

    async def _create_and_send_backup(self, bot, chat_id: int, *, prefix: str = "vps-bill", caption: str | None = None):
        raw, archive, metadata = create_backup_archive(self.db, self.settings.backups_dir, prefix=prefix)
        size_mb = archive.stat().st_size / (1024 * 1024)
        text = caption or (
            f"{e(self.emojis, 'backup')} <b>Резервная копия VPS Bill</b>\n\n"
            f"Версия: <code>{h(metadata['version'])}</code>\n"
            f"Размер архива: <code>{size_mb:.2f} MB</code>\n"
            f"Проверка базы: <b>OK</b>"
        )
        await bot.send_document(
            chat_id=chat_id,
            document=FSInputFile(archive),
            caption=text,
        )
        return raw, archive, metadata

    def _main_text(self) -> str:
        emojis = self.emojis
        servers = self.db.list_servers()
        overdue = [s for s in servers if date.fromisoformat(s["next_due"]) < self.today]
        soon = [s for s in servers if 0 <= (date.fromisoformat(s["next_due"]) - self.today).days <= 7]
        month_start = self.today.replace(day=1)
        next_month = date(month_start.year + 1, 1, 1) if month_start.month == 12 else date(month_start.year, month_start.month + 1, 1)
        paid = self.db.payments_between(month_start.isoformat(), next_month.isoformat())
        totals = sum_by_currency(paid)
        order = ("RUB", "EUR", "USD")
        spent = " · ".join(money(totals[cur], cur) for cur in order if totals.get(cur)) or "0"
        text = (
            f"{e(emojis, 'brand')} <b>VPS BILL</b>\n\n"
            f"Серверов: <b>{len(servers)}</b>\n"
            f"К оплате в течение недели: <b>{len(soon)}</b>\n"
            f"Просрочено: <b>{len(overdue)}</b>\n"
            f"Оплачено в этом месяце: <b>{h(spent)}</b>"
        )
        if self.db.monitoring_enabled():
            down = self.db.down_monitored_servers()
            if down:
                names = "\n".join(f"• {h(s['name'])}" for s in down[:8])
                more = f"\n• и ещё {len(down) - 8}" if len(down) > 8 else ""
                text += (
                    f"\n\n{e(emojis, 'status_down')} <b>Недоступны: {len(down)}</b>\n"
                    f"{names}{more}"
                )
        return text

    async def _show_main_cb(self, q: CallbackQuery, state: FSMContext | None = None):
        if state:
            await state.clear()
        await q.answer()
        emojis = self.emojis
        await q.message.edit_text(self._main_text(), reply_markup=main_menu(emojis))

    def _register(self):
        r = self.router
        r.message.register(self.start, CommandStart())
        r.message.register(self.start, Command("menu"))

        r.callback_query.register(self.noop, F.data == "noop")
        r.callback_query.register(self.cancel_flow, F.data == "flow:cancel")
        r.callback_query.register(self._show_main_cb, F.data == "main")

        r.callback_query.register(self.servers, (F.data == "servers") | F.data.startswith("servers:page:"))
        r.callback_query.register(self.server, F.data.startswith("srvopen:"))
        r.callback_query.register(self.server, F.data.startswith("server:"))  # legacy callbacks from old messages
        r.callback_query.register(self.upcoming, F.data == "upcoming")
        r.callback_query.register(self.payments, F.data == "payments")
        r.callback_query.register(self.analytics, F.data == "analytics")

        r.callback_query.register(self.settings_page, F.data == "settings")
        r.callback_query.register(self.reminders_page, F.data == "settings:reminders")
        r.callback_query.register(self.billing_cycles_page, F.data == "settings:billing_cycles")
        r.callback_query.register(self.billing_cycle_toggle, F.data.startswith("billcycle:toggle:"))
        r.callback_query.register(self.billing_cycle_default, F.data == "billcycle:default")
        r.callback_query.register(self.currencies_page, F.data == "settings:currencies")
        r.callback_query.register(self.currency_toggle, F.data.startswith("currency:toggle:"))
        r.callback_query.register(self.currency_default, F.data == "currency:default")
        r.callback_query.register(self.currency_add_start, F.data == "currency:add")
        r.message.register(self.currency_add_input, CurrencyAdd.waiting)
        r.callback_query.register(self.reminder_toggle, F.data.startswith("rem:toggle:"))
        r.callback_query.register(self.reminder_overdue_toggle, F.data == "rem:overdue")
        r.callback_query.register(self.reminder_default, F.data == "rem:default")
        r.callback_query.register(self.reminder_time_set, F.data.startswith("rem:time:"))
        r.message.register(self.reminder_time_input, ReminderTimeInput.waiting)
        r.callback_query.register(self.reports_page, F.data == "settings:reports")
        r.callback_query.register(self.monitoring_page, F.data == "settings:monitoring")
        r.callback_query.register(self.monitor_global_toggle, F.data == "monitor:global")
        r.callback_query.register(self.monitor_enable_all, F.data == "monitor:enableall")
        r.callback_query.register(self.monitor_method_set, F.data.startswith("monitor:method:"))
        r.callback_query.register(self.monitor_tcp_port_start, F.data == "monitor:tcpport")
        r.callback_query.register(self.monitor_tcp_port_cancel, F.data == "monitor:tcpport:cancel")
        r.message.register(self.monitor_tcp_port_input, MonitorTcpPort.waiting)
        r.callback_query.register(self.monitor_interval_set, F.data.startswith("monitor:interval:"))
        r.callback_query.register(self.monitor_failures_set, F.data.startswith("monitor:failures:"))
        r.callback_query.register(self.monitor_recovery_set, F.data.startswith("monitor:recovery:"))
        r.callback_query.register(self.monitor_server_toggle, F.data.startswith("monitor:server:"))
        r.callback_query.register(self.report_toggle, F.data == "report:toggle")
        r.callback_query.register(self.report_day, F.data.startswith("report:day:"))
        r.message.register(self.report_day_input, ReportDayInput.waiting)
        r.callback_query.register(self.report_time, F.data.startswith("report:time:"))
        r.message.register(self.report_time_input, ReportTimeInput.waiting)
        r.callback_query.register(self.report_manual, F.data == "report:manual")
        r.message.register(self.report_manual_input, ReportScheduleInput.waiting)
        r.callback_query.register(self.report_default, F.data == "report:default")
        r.callback_query.register(self.emojis_page, (F.data == "settings:emojis") | F.data.startswith("emoji:page:"))
        r.callback_query.register(self.emoji_resetall_ask, (F.data == "emoji:resetall") | F.data.startswith("emoji:resetall:p:"))
        r.callback_query.register(self.emoji_resetall_yes, F.data.startswith("emoji:resetall:yes"))
        r.callback_query.register(self.emoji_reset, F.data.startswith("emoji:reset:"))
        r.callback_query.register(self.emoji_cancel, F.data == "emoji:cancel")
        r.callback_query.register(self.emoji_edit, F.data.startswith("emoji:edit:"))
        r.message.register(self.emoji_input, EmojiEdit.waiting)
        r.callback_query.register(self.backups_page, F.data == "settings:backups")
        r.callback_query.register(self.backup, F.data.in_({"backup", "backup:create"}))
        r.callback_query.register(self.backup_cleanup, F.data == "backup:cleanup")
        r.callback_query.register(self.update_page, F.data == "settings:update")
        r.callback_query.register(self.update_check, F.data == "update:check")
        r.callback_query.register(self.update_install, F.data.startswith("update:install:"))
        r.callback_query.register(self.update_confirm, F.data.startswith("update:confirm:"))
        r.callback_query.register(self.update_tomorrow, F.data.startswith("update:tomorrow:"))
        r.callback_query.register(self.update_ignore, F.data.startswith("update:ignore:"))
        r.callback_query.register(self.dictionaries_page, F.data == "settings:dictionaries")
        r.callback_query.register(self.demo_add_ask, F.data == "demo:add:ask")
        r.callback_query.register(self.demo_add_yes, F.data == "demo:add:yes")
        r.callback_query.register(self.demo_remove_ask, F.data == "demo:remove:ask")
        r.callback_query.register(self.demo_remove_yes, F.data == "demo:remove:yes")
        r.callback_query.register(self.dictionary_list, F.data.in_({"dict:provider", "dict:country", "dict:tag"}))
        r.callback_query.register(self.dictionary_item, F.data.startswith("dict:item:"))
        r.callback_query.register(self.dictionary_delete_ask, F.data.startswith("dict:delete:ask:"))
        r.callback_query.register(self.dictionary_delete_yes, F.data.startswith("dict:delete:yes:"))
        r.callback_query.register(self.dictionary_rename_start, F.data.startswith("dict:rename:"))
        r.message.register(self.dictionary_rename_input, DictionaryRename.waiting)
        r.callback_query.register(self.provider_url_start, F.data.startswith("dict:url:"))
        r.message.register(self.provider_url_input, ProviderUrlInput.waiting)

        r.callback_query.register(self.paid, F.data.startswith("paid:"))
        r.callback_query.register(self.balance_topup_start, F.data.startswith("balance:topup:"))
        r.message.register(self.balance_topup_input, BalanceTopup.waiting)
        r.callback_query.register(self.snooze, F.data.startswith("snooze:"))
        r.callback_query.register(self.server_details, F.data.startswith("details:"))
        r.callback_query.register(self.country_choose, F.data.startswith("country:choose:"))
        r.callback_query.register(self.country_set, F.data.startswith("country:set:"))
        r.callback_query.register(self.tag_choose, F.data.startswith("tag:choose:"))
        r.callback_query.register(self.tag_toggle, F.data.startswith("tag:toggle:"))
        r.callback_query.register(self.tag_new, F.data.startswith("tag:new:"))
        r.callback_query.register(self.edit_server_back, F.data.startswith("editback:"))
        r.callback_query.register(self.edit_server_field, F.data.startswith("editfield:"))
        r.message.register(self.edit_server_field_input, EditServerField.waiting)
        r.callback_query.register(self.archive_page, (F.data == "archive") | F.data.startswith("archive:page:"))
        r.callback_query.register(self.archive_item, F.data.startswith("archiveitem:"))
        r.callback_query.register(self.archive_ask, F.data.startswith("archiveask:"))
        r.callback_query.register(self.archive_yes, F.data.startswith("archiveyes:"))
        r.callback_query.register(self.archive_restore, F.data.startswith("archiverestore:"))
        r.callback_query.register(self.archive_to_trash, F.data.startswith("archivetotrash:"))
        r.callback_query.register(self.trash_page, (F.data == "trash") | F.data.startswith("trash:page:"))
        r.callback_query.register(self.trash_item, F.data.startswith("trashitem:"))
        r.callback_query.register(self.trash_ask, F.data.startswith("trashask:"))
        r.callback_query.register(self.trash_yes, F.data.startswith("trashyes:"))
        r.callback_query.register(self.restore_server, F.data.startswith("restore:"))
        r.callback_query.register(self.purge_ask, F.data.startswith("purgeask:"))
        r.callback_query.register(self.purge_yes, F.data.startswith("purgeyes:"))
        r.callback_query.register(self.purge_all_ask, F.data == "trash:purgeall:ask")
        r.callback_query.register(self.purge_all_yes, F.data == "trash:purgeall:yes")

        r.callback_query.register(self.add_start, F.data == "add:start")
        r.message.register(self.add_name, AddServer.name)
        r.callback_query.register(self.add_provider_select, AddServer.provider, F.data.startswith("provsel:"))
        r.callback_query.register(self.add_provider_new, AddServer.provider, F.data == "prov:new")
        r.message.register(self.add_provider, AddServer.provider)
        r.message.register(self.add_amount, AddServer.amount)
        r.callback_query.register(self.add_daily_mode, AddServer.daily_mode, F.data.startswith("daily:"))
        r.callback_query.register(self.add_currency, AddServer.currency, F.data.startswith("cur:"))
        r.message.register(self.add_balance, AddServer.balance)
        r.callback_query.register(self.add_balance_alert, AddServer.balance_alert, F.data.startswith("balancealert:"))
        r.callback_query.register(self.calendar_nav_add, AddServer.due, F.data.startswith("cal:add:nav:"))
        r.callback_query.register(self.calendar_day_add, AddServer.due, F.data.startswith("cal:add:day:"))
        r.callback_query.register(self.add_cycle, AddServer.cycle, F.data.startswith("cycle:"))
        r.callback_query.register(self.add_record_current, AddServer.record_current, F.data.startswith("addpay:"))

        r.callback_query.register(self.change_date_start, F.data.startswith("date:"))
        r.callback_query.register(self.calendar_nav_date, ChangeDate.due, F.data.startswith("cal:date:nav:"))
        r.callback_query.register(self.calendar_day_date, ChangeDate.due, F.data.startswith("cal:date:day:"))

    async def noop(self, q: CallbackQuery):
        await q.answer()

    async def start(self, m: Message, state: FSMContext):
        await state.clear()
        emojis = self.emojis
        await m.answer(self._main_text(), reply_markup=main_menu(emojis))

    async def cancel_flow(self, q: CallbackQuery, state: FSMContext):
        await state.clear()
        await q.answer("Отменено")
        emojis = self.emojis
        await q.message.edit_text(self._main_text(), reply_markup=main_menu(emojis))

    async def servers(self, q: CallbackQuery):
        await q.answer()
        emojis = self.emojis
        items = self.db.list_servers()
        page_size = 8
        page = 0
        if q.data and q.data.startswith("servers:page:"):
            try:
                page = int(q.data.rsplit(":", 1)[1])
            except ValueError:
                page = 0
        total_pages = max(1, (len(items) + page_size - 1) // page_size)
        page = max(0, min(page, total_pages - 1))
        start = page * page_size
        rows = []
        for server in items[start:start + page_size]:
            d = (date.fromisoformat(server["next_due"]) - self.today).days
            if str(server.get("billing_mode") or "scheduled") == "balance":
                remaining = self.db.balance_remaining_minor(server, self.today)
                days_left = remaining // max(1, int(server.get("amount_minor") or 1))
                label = f"{server['name']} · баланс на ~{days_left} дн."
                style = "primary" if days_left <= int(server.get("balance_alert_days") or 3) else "success"
            elif d < 0:
                label = f"{server['name']} · просрочено {abs(d)} дн."
                style = "danger"
            elif 0 <= d <= 7:
                label = f"{server['name']} · {'сегодня' if d == 0 else date.fromisoformat(server['next_due']).strftime('%d.%m.%y')}"
                style = "primary"
            else:
                label = f"{server['name']} · {date.fromisoformat(server['next_due']).strftime('%d.%m.%y')}"
                style = "success"
            rows.append([button(emojis, "server", label, f"srvopen:{server['id']}", style=style)])
        nav = pagination_row(emojis, page, total_pages, "servers:page")
        if nav:
            rows.append(nav)
        archive_n = self.db.archive_count()
        archive_label = f"Архив · {archive_n}" if archive_n else "Архив"
        rows.append([button(emojis, "server", archive_label, "archive")])
        trash_n = self.db.trash_count()
        if trash_n:
            rows.append([button(emojis, "trash", f"Корзина · {trash_n}", "trash")])
        rows.append([button(emojis, "back", "Главное меню", "main")])
        overdue = sum(1 for x in items if date.fromisoformat(x["next_due"]) < self.today)
        text = f"{e(emojis, 'server')} <b>Серверы</b>\n\nАктивных: <b>{len(items)}</b>"
        if overdue:
            text += f" · {e(emojis, 'status_overdue')} просрочено: <b>{overdue}</b>"
        if total_pages > 1:
            text += f"\nСтраница: <b>{page + 1}/{total_pages}</b>"
        if not items:
            text += "\n\nПока серверов нет."
        await q.message.edit_text(text, reply_markup=kb(rows))

    async def server(self, q: CallbackQuery):
        data = str(q.data or "")
        try:
            sid = int(data.split(":", 1)[1])
        except (IndexError, ValueError):
            return await q.answer("Некорректная карточка сервера", show_alert=True)
        s = self.db.get_server(sid)
        emojis = self.emojis
        if not s:
            await q.answer("Сервер не найден", show_alert=True)
            return
        try:
            await q.message.edit_text(
                server_card(s, emojis),
                reply_markup=server_buttons(sid, emojis, balance_mode=str(s.get("billing_mode") or "") == "balance"),
            )
            await q.answer()
        except Exception as exc:
            print(f"server card open failed sid={sid}: {exc!r}", flush=True)
            await q.answer("Не удалось открыть карточку. Ошибка записана в лог.", show_alert=True)

    async def upcoming(self, q: CallbackQuery):
        await q.answer()
        emojis = self.emojis
        items = [s for s in self.db.list_servers() if (date.fromisoformat(s["next_due"]) - self.today).days <= 30]
        lines = [f"{e(emojis, 'calendar')} <b>Ближайшие оплаты</b>", ""]
        for s in items[:30]:
            d = (date.fromisoformat(s["next_due"]) - self.today).days
            provider = str(s.get("provider") or "").strip()
            provider_url = self.db.provider_url(provider) if provider else ""
            if provider:
                if provider_url:
                    provider_text = f'<a href="{h(provider_url)}">{h(provider)}</a> {e(emojis, "cabinet")}'
                else:
                    provider_text = h(provider)
                lines.append(f"<b>{h(s['name'])}</b> - {provider_text}")
            else:
                lines.append(f"<b>{h(s['name'])}</b>")
            lines.append(
                f"↳ · {h(relative_due(d))} · {date.fromisoformat(s['next_due']).strftime('%d.%m.%Y')} · {h(compact_money(s['amount_minor'], s['currency']))} ·"
            )
            note = str(s.get("notes") or "").strip()
            if note:
                lines.append(f"↳ {e(emojis, 'notes')} {h(note)}")
            lines.append("")
        if len(lines) == 2:
            lines.append("На ближайшие 30 дней оплат нет.")
        await q.message.edit_text("\n".join(lines).rstrip(), reply_markup=back_main(emojis), disable_web_page_preview=True)

    async def payments(self, q: CallbackQuery):
        await q.answer()
        emojis = self.emojis
        rows = self.db.recent_payments(25)
        lines = [f"{e(emojis, 'payments')} <b>История оплат</b>", ""]
        for p in rows:
            pd = datetime.fromisoformat(p["paid_at"]).strftime("%d.%m.%y")
            lines.append(f"• {pd} · <b>{h(p['name'])}</b> · {money(p['amount_minor'], p['currency'])}")
        if len(lines) == 2:
            lines.append("Оплат пока нет.")
        await q.message.edit_text("\n".join(lines), reply_markup=back_main(emojis))

    async def analytics(self, q: CallbackQuery):
        await q.answer()
        emojis = self.emojis
        today = self.today
        servers = self.db.list_servers()
        month_start = today.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        paid = self.db.payments_between(month_start.isoformat(), next_month.isoformat())
        upcoming = self.db.due_between(today.isoformat(), (today + timedelta(days=30)).isoformat())
        overdue = [s for s in servers if date.fromisoformat(s["next_due"]) < today]
        due7 = [s for s in servers if 0 <= (date.fromisoformat(s["next_due"]) - today).days <= 7]

        pt = sum_by_currency(paid)
        ut = sum_by_currency(upcoming)
        od = sum_by_currency(overdue)
        monthly: dict[str, int] = {"RUB": 0, "EUR": 0, "USD": 0}
        annual: dict[str, int] = {"RUB": 0, "EUR": 0, "USD": 0}
        providers: dict[str, dict] = {}
        tag_set: set[str] = set()
        for srv in servers:
            cur = srv["currency"].upper()
            monthly_value = monthly_equivalent_minor(srv["amount_minor"], srv["cycle"], srv.get("cycle_days"))
            annual_value = annual_equivalent_minor(srv["amount_minor"], srv["cycle"], srv.get("cycle_days"))
            monthly[cur] = monthly.get(cur, 0) + monthly_value
            annual[cur] = annual.get(cur, 0) + annual_value
            provider = str(srv.get("provider") or "Без хостера")
            item = providers.setdefault(provider, {"count": 0, "monthly": {}})
            item["count"] += 1
            item["monthly"][cur] = item["monthly"].get(cur, 0) + monthly_value
            tag_set.update(x.strip().casefold() for x in str(srv.get("tags") or "").split(",") if x.strip())

        def money_lines(values: dict[str, int]) -> list[str]:
            rows = [f"  {money(values[c], c)}" for c in ("RUB", "EUR", "USD") if values.get(c)]
            extras = [c for c in sorted(values) if c not in {"RUB", "EUR", "USD"} and values.get(c)]
            rows.extend(f"  {money(values[c], c)}" for c in extras)
            return rows or ["  0"]

        lines = [
            f"{e(emojis, 'analytics')} <b>Аналитика</b>",
            "",
            "<b>Парк</b>",
            f"{e(emojis, 'server')} {len(servers)} VPS · {e(emojis, 'provider')} {len(providers)} хостеров · {e(emojis, 'tags')} {len(tag_set)} тегов",
            f"{e(emojis, 'status_overdue')} {len(overdue)} просрочено · {e(emojis, 'calendar')} {len(due7)} оплат в течение недели",
            "",
            "<b>Факт · этот месяц</b>",
            *money_lines(pt),
            "",
            "<b>Ближайшие 30 дней</b>",
            *money_lines(ut),
            "",
            "<b>Регулярный бюджет · ≈ в месяц</b>",
            *money_lines(monthly),
            "",
            "<b>Эквивалент · ≈ в год</b>",
            *money_lines(annual),
        ]
        if overdue:
            lines += ["", f"{e(emojis, 'status_overdue')} <b>Просрочено</b>", *money_lines(od)]
        if providers:
            lines += ["", f"{e(emojis, 'provider')} <b>Хостеры</b>"]
            ranked = sorted(providers.items(), key=lambda x: (-int(x[1]["count"]), x[0].casefold()))[:8]
            for name, info in ranked:
                provider_text = h(name)
                totals = []
                for cur in ("RUB", "EUR", "USD"):
                    if info["monthly"].get(cur):
                        totals.append(f"{compact_money(info['monthly'][cur], cur)}/мес.")
                for cur in sorted(info["monthly"]):
                    if cur not in {"RUB", "EUR", "USD"} and info["monthly"].get(cur):
                        totals.append(f"{compact_money(info['monthly'][cur], cur)}/мес.")
                suffix = " · ".join(totals) if totals else "0/мес."
                lines.append(f"{provider_text}\n↳ {info['count']} VPS · {h(suffix)}")
        await q.message.edit_text("\n".join(lines), reply_markup=back_main(emojis), disable_web_page_preview=True)

    async def settings_page(self, q: CallbackQuery):
        await q.answer()
        emojis = self.emojis
        dbi = self.db.integrity()
        reminder_text = ", ".join(str(x) for x in self.db.get_reminder_days()) or "выключены"
        cycle_labels = {
            "daily": "день", "weekly": "неделя", "monthly": "месяц",
            "quarterly": "3 мес.", "semiannual": "6 мес.", "yearly": "год",
        }
        cycle_text = ", ".join(cycle_labels.get(x, x) for x in self.db.get_billing_cycles())
        text = (
            f"{e(emojis, 'settings')} <b>Настройки</b>\n\n"
            f"База: <b>{'OK' if dbi['integrity'] == 'ok' else h(dbi['integrity'])}</b>\n"
            f"Напоминания: <b>{h(reminder_text)}</b>\n"
            f"Периоды: <b>{h(cycle_text)}</b>\n"
            f"Версия бота: <b>{h(__version__)}</b>"
        )
        await q.message.edit_text(text, reply_markup=settings_keyboard(emojis))

    def _dictionary_items(self, kind: str) -> list[str]:
        if kind == "provider":
            return self.db.list_providers()
        if kind == "country":
            return self.db.used_countries()
        if kind == "tag":
            return self.db.used_tags()
        return []

    def _dictionary_title(self, kind: str) -> str:
        return {"provider": "Хостеры", "country": "Страны", "tag": "Теги"}.get(kind, "Справочник")

    async def dictionaries_page(self, q: CallbackQuery):
        await q.answer()
        demo_count = self.db.demo_server_count()
        text = (
            f"{e(self.emojis, 'dictionaries')} <b>Справочники</b>\n\n"
            "Здесь можно управлять хостерами, странами, тегами и premium emoji. "
            "Переименование справочников применяется сразу ко всем VPS.\n\n"
            f"Демо-серверы: <b>{demo_count}</b>"
        )
        await q.message.edit_text(
            text,
            reply_markup=dictionaries_keyboard(self.emojis, demo_present=demo_count > 0),
        )

    async def demo_add_ask(self, q: CallbackQuery):
        await q.answer()
        if self.db.demo_server_count():
            return await q.answer("Демо-серверы уже добавлены", show_alert=True)
        text = (
            f"{e(self.emojis, 'server')} <b>Добавить демо-серверы?</b>\n\n"
            "Будет создано 6 полностью заполненных тестовых VPS со сроками оплаты относительно сегодняшней даты:\n"
            "• просрочен на 5 дней\n"
            "• сегодня\n"
            "• завтра\n"
            "• через 3 дня\n"
            "• через 7 дней\n"
            "• через 30 дней\n\n"
            "У них будут IP, хостер, страна, теги и заметки. Мониторинг будет выключен."
        )
        await q.message.edit_text(text, reply_markup=demo_confirm_keyboard("add", self.emojis))

    async def demo_add_yes(self, q: CallbackQuery):
        await q.answer()
        added = self.db.add_demo_servers(self.today)
        await q.message.edit_text(
            f"{e(self.emojis, 'server')} <b>Демо-серверы добавлены</b>\n\nСоздано VPS: <b>{added}</b>",
            reply_markup=dictionaries_keyboard(self.emojis, demo_present=self.db.demo_server_count() > 0),
        )

    async def demo_remove_ask(self, q: CallbackQuery):
        await q.answer()
        count = self.db.demo_server_count()
        if not count:
            return await q.answer("Демо-серверов нет", show_alert=True)
        ids = set(self.db.demo_server_ids())
        names = [s["name"] for s in self.db.list_servers(active_only=False) if int(s["id"]) in ids]
        lines = "\n".join(f"• {h(name)}" for name in names)
        text = (
            f"{e(self.emojis, 'warning')} <b>Удалить все демо-серверы?</b>\n\n"
            f"Будет полностью удалено: <b>{count}</b>\n\n{lines}\n\n"
            "Реальные VPS и их платежи не затрагиваются."
        )
        await q.message.edit_text(text, reply_markup=demo_confirm_keyboard("remove", self.emojis))

    async def demo_remove_yes(self, q: CallbackQuery):
        await q.answer()
        removed = self.db.delete_demo_servers()
        await q.message.edit_text(
            f"{e(self.emojis, 'delete')} <b>Демо-серверы удалены</b>\n\nУдалено VPS: <b>{removed}</b>",
            reply_markup=dictionaries_keyboard(self.emojis, demo_present=False),
        )

    async def dictionary_list(self, q: CallbackQuery):
        await q.answer()
        kind = q.data.split(":", 1)[1]
        items = self._dictionary_items(kind)
        title = self._dictionary_title(kind)
        text = f"<b>{h(title)}</b>\n\nВыбери значение, которое нужно изменить."
        if not items:
            text += "\n\nПока список пуст."
        await q.message.edit_text(text, reply_markup=dictionary_items_keyboard(kind, items, self.emojis))

    async def dictionary_item(self, q: CallbackQuery):
        await q.answer()
        try:
            _, _, kind, raw_idx = q.data.split(":", 3)
            idx = int(raw_idx)
        except (ValueError, IndexError):
            return await q.answer("Элемент не найден", show_alert=True)
        items = self._dictionary_items(kind)
        if idx < 0 or idx >= len(items):
            return await q.answer("Список изменился. Открой его заново.", show_alert=True)
        value = items[idx]
        provider_url = self.db.provider_url(value) if kind == "provider" else ""
        extra = ""
        if kind == "provider":
            extra = f"\nСсылка на ЛК: {'<a href="' + h(provider_url) + '">открыть</a>' if provider_url else '<b>не задана</b>'}"
        await q.message.edit_text(
            f"<b>{h(self._dictionary_title(kind))}</b>\n\nТекущее значение: <b>{h(value)}</b>{extra}",
            reply_markup=dictionary_edit_keyboard(kind, idx, self.emojis, provider_url),
            disable_web_page_preview=True,
        )

    async def dictionary_delete_ask(self, q: CallbackQuery):
        await q.answer()
        try:
            _, _, _, kind, raw_idx = q.data.split(":", 4)
            idx = int(raw_idx)
        except (ValueError, IndexError):
            return await q.answer("Элемент не найден", show_alert=True)
        if kind not in {"country", "tag"}:
            return await q.answer("Удаление недоступно", show_alert=True)
        items = self._dictionary_items(kind)
        if idx < 0 or idx >= len(items):
            return await q.answer("Список изменился. Открой его заново.", show_alert=True)
        value = items[idx]
        servers = self.db.servers_with_country(value) if kind == "country" else self.db.servers_with_tag(value)
        names = [str(row.get("name") or f"VPS #{row.get('id')}") for row in servers]
        shown = names[:20]
        server_lines = "\n".join(f"• {h(name)}" for name in shown)
        if len(names) > len(shown):
            server_lines += f"\n• … и ещё {len(names) - len(shown)}"
        if kind == "country":
            consequence = "У этих VPS поле <b>Страна</b> будет очищено."
        else:
            consequence = (
                "У этих VPS тег будет удалён из поля <b>Теги</b>. "
                "Остальные теги сохранятся; если этот тег был единственным, поле станет пустым."
            )
        text = (
            f"{e(self.emojis, 'warning')} <b>Удалить {h(value)}?</b>\n\n"
            f"Используется на VPS: <b>{len(names)}</b>\n"
        )
        if server_lines:
            text += f"\n{server_lines}\n"
        text += f"\n{consequence}\n\nТочно удалить?"
        await q.message.edit_text(
            text,
            reply_markup=dictionary_delete_confirm_keyboard(kind, idx, self.emojis),
        )

    async def dictionary_delete_yes(self, q: CallbackQuery):
        await q.answer()
        try:
            _, _, _, kind, raw_idx = q.data.split(":", 4)
            idx = int(raw_idx)
        except (ValueError, IndexError):
            return await q.answer("Элемент не найден", show_alert=True)
        if kind not in {"country", "tag"}:
            return await q.answer("Удаление недоступно", show_alert=True)
        items = self._dictionary_items(kind)
        if idx < 0 or idx >= len(items):
            return await q.answer("Список изменился. Открой его заново.", show_alert=True)
        value = items[idx]
        changed = self.db.delete_country(value) if kind == "country" else self.db.delete_tag(value)
        title = "Страна удалена" if kind == "country" else "Тег удалён"
        await q.message.edit_text(
            f"{e(self.emojis, 'delete')} <b>{title}</b>\n\n"
            f"{h(value)}\n"
            f"Обновлено VPS: <b>{changed}</b>",
            reply_markup=dictionary_items_keyboard(kind, self._dictionary_items(kind), self.emojis),
        )

    async def dictionary_rename_start(self, q: CallbackQuery, state: FSMContext):
        await q.answer()
        try:
            _, _, kind, raw_idx = q.data.split(":", 3)
            idx = int(raw_idx)
        except (ValueError, IndexError):
            return await q.answer("Элемент не найден", show_alert=True)
        items = self._dictionary_items(kind)
        if idx < 0 or idx >= len(items):
            return await q.answer("Список изменился. Открой его заново.", show_alert=True)
        old = items[idx]
        await state.update_data(dict_kind=kind, dict_old=old)
        await state.set_state(DictionaryRename.waiting)
        await q.message.edit_text(
            f"{e(self.emojis, 'edit')} Переименовать <b>{h(old)}</b>\n\nВведите новое название:",
            reply_markup=cancel_keyboard(self.emojis),
        )

    async def dictionary_rename_input(self, m: Message, state: FSMContext):
        value = " ".join((m.text or "").strip().split())
        if not value:
            return await m.answer("Название не может быть пустым.")
        data = await state.get_data()
        kind = str(data.get("dict_kind") or "")
        old = str(data.get("dict_old") or "")
        try:
            if kind == "provider":
                changed = self.db.rename_provider(old, value)
            elif kind == "country":
                changed = self.db.rename_country(old, value)
            elif kind == "tag":
                changed = self.db.rename_tag(old, value)
            else:
                raise ValueError("Неизвестный справочник")
        except ValueError as exc:
            return await m.answer(h(str(exc)))
        await state.clear()
        await m.answer(
            f"{e(self.emojis, 'paid')} <b>Изменено</b>\n\n"
            f"{h(old)} → <b>{h(value)}</b>\n"
            f"Обновлено VPS: <b>{changed}</b>",
            reply_markup=dictionaries_keyboard(self.emojis),
        )

    async def provider_url_start(self, q: CallbackQuery, state: FSMContext):
        await q.answer()
        try:
            idx = int(q.data.rsplit(":", 1)[1])
        except ValueError:
            return await q.answer("Хостер не найден", show_alert=True)
        items = self.db.list_providers()
        if idx < 0 or idx >= len(items):
            return await q.answer("Список изменился. Открой его заново.", show_alert=True)
        provider = items[idx]
        current = self.db.provider_url(provider)
        await state.update_data(provider_url_name=provider)
        await state.set_state(ProviderUrlInput.waiting)
        current_text = f'<a href="{h(current)}">{h(current)}</a>' if current else "не задана"
        await q.message.edit_text(
            f"{e(self.emojis, 'provider')} <b>{h(provider)}</b>\n\n"
            f"Ссылка на личный кабинет: {current_text}\n\n"
            "Отправьте сайт, <code>t.me/имя</code> или <code>@имя_бота</code>.\n"
            "Для очистки поля отправьте: -",
            reply_markup=cancel_keyboard(self.emojis),
            disable_web_page_preview=True,
        )

    async def provider_url_input(self, m: Message, state: FSMContext):
        data = await state.get_data()
        provider = str(data.get("provider_url_name") or "")
        value = str(m.text or "").strip()
        if value == "-":
            value = ""
        try:
            self.db.set_provider_url(provider, value)
        except ValueError as exc:
            return await m.answer(f"{e(self.emojis, 'warning')} {h(exc)}", reply_markup=cancel_keyboard(self.emojis))
        await state.clear()
        url_text = "удалена" if not value else "сохранена"
        await m.answer(
            f"{e(self.emojis, 'paid')} Ссылка на ЛК для <b>{h(provider)}</b> {url_text}.",
            reply_markup=dictionaries_keyboard(self.emojis),
        )

    async def billing_cycles_page(self, q: CallbackQuery):
        await q.answer()
        emojis = self.emojis
        enabled = self.db.get_billing_cycles()
        labels_map = {
            "daily": "ежедневно",
            "weekly": "1 неделя",
            "monthly": "1 месяц",
            "quarterly": "3 месяца",
            "semiannual": "6 месяцев",
            "yearly": "1 год",
        }
        labels = [labels_map[x] for x in enabled if x in labels_map]
        text = (
            f"{e(emojis, 'cycle')} <b>Периоды</b>\n\n"
            "Выбери галочками, какие сроки показывать при создании VPS. "
            "Изменения применяются сразу.\n\n"
            f"Сейчас: <b>{h(', '.join(labels))}</b>"
        )
        await q.message.edit_text(text, reply_markup=billing_cycles_keyboard(enabled, emojis))

    async def billing_cycle_toggle(self, q: CallbackQuery):
        cycle = q.data.rsplit(":", 1)[1]
        allowed = {"daily", "weekly", "monthly", "quarterly", "semiannual", "yearly"}
        if cycle not in allowed:
            return await q.answer("Неизвестный период", show_alert=True)
        enabled = set(self.db.get_billing_cycles())
        if cycle in enabled:
            if len(enabled) == 1:
                return await q.answer("Должен остаться хотя бы один период", show_alert=True)
            enabled.remove(cycle)
        else:
            enabled.add(cycle)
        self.db.set_billing_cycles(tuple(enabled))
        await self.billing_cycles_page(q)

    async def billing_cycle_default(self, q: CallbackQuery):
        self.db.set_billing_cycles(("weekly", "monthly", "quarterly", "yearly"))
        await self.billing_cycles_page(q)

    async def currencies_page(self, q: CallbackQuery, state: FSMContext | None = None):
        if state:
            await state.clear()
        await q.answer()
        rows = self.db.list_currencies()
        active = [r["code"] for r in rows if r["active"]]
        text = (
            f"{e(self.emojis, 'money')} <b>Валюты</b>\n\n"
            "Зелёные - используются при создании VPS. Белые - выключены.\n"
            "Можно добавить свою валюту.\n\n"
            f"Активны: <b>{h(', '.join(active))}</b>"
        )
        await q.message.edit_text(text, reply_markup=currencies_settings_keyboard(rows, self.emojis))

    async def currency_toggle(self, q: CallbackQuery):
        code = q.data.rsplit(":", 1)[1].upper()
        try:
            self.db.toggle_currency(code)
        except ValueError as exc:
            return await q.answer(str(exc), show_alert=True)
        await self.currencies_page(q)

    async def currency_default(self, q: CallbackQuery):
        self.db.reset_currencies()
        await self.currencies_page(q)

    async def currency_add_start(self, q: CallbackQuery, state: FSMContext):
        await q.answer()
        await state.set_state(CurrencyAdd.waiting)
        await q.message.edit_text(
            f"{e(self.emojis, 'money')} <b>Добавить валюту</b>\n\n"
            "Отправьте короткий код валюты, например <code>GBP</code>, <code>CHF</code> или <code>USDT</code>.",
            reply_markup=cancel_keyboard(self.emojis),
        )

    async def currency_add_input(self, m: Message, state: FSMContext):
        code = (m.text or "").strip().upper()
        try:
            self.db.add_currency(code)
        except ValueError as exc:
            return await m.answer(f"{e(self.emojis, 'warning')} {h(exc)}", reply_markup=cancel_keyboard(self.emojis))
        await state.clear()
        rows = self.db.list_currencies()
        await m.answer(
            f"{e(self.emojis, 'paid')} Валюта <b>{h(code)}</b> добавлена и включена.",
            reply_markup=currencies_settings_keyboard(rows, self.emojis),
        )

    async def reminders_page(self, q: CallbackQuery):
        await q.answer()
        emojis = self.emojis
        days = self.db.get_reminder_days()
        labels = ["в день оплаты" if d == 0 else f"за {d} дн." for d in days]
        reminder_time = self.db.payment_reminder_time()
        text = (
            f"{e(emojis, 'reminders')} <b>Напоминания</b>\n\n"
            "Нажимай варианты - изменения применяются сразу.\n\n"
            f"Сейчас: <b>{h(', '.join(labels) or 'выключены')}</b>\n"
            f"Время уведомления: <b>{h(reminder_time)}</b>\n"
            f"Просрочка ежедневно: <b>{'да' if self.db.overdue_daily() else 'нет'}</b>"
        )
        await q.message.edit_text(text, reply_markup=reminder_keyboard(days, self.db.overdue_daily(), reminder_time, emojis))

    async def reminder_toggle(self, q: CallbackQuery):
        d = int(q.data.rsplit(":", 1)[1])
        days = set(self.db.get_reminder_days())
        if d in days:
            days.remove(d)
        else:
            days.add(d)
        self.db.set_reminder_days(tuple(days))
        await self.reminders_page(q)

    async def reminder_overdue_toggle(self, q: CallbackQuery):
        self.db.set_setting("overdue_daily", "0" if self.db.overdue_daily() else "1")
        await self.reminders_page(q)

    async def reminder_default(self, q: CallbackQuery):
        self.db.set_reminder_days((7, 3, 1, 0))
        self.db.set_setting("overdue_daily", "1")
        self.db.set_payment_reminder_time("10:00")
        await self.reminders_page(q)

    async def reminder_time_set(self, q: CallbackQuery, state: FSMContext):
        suffix = q.data.rsplit(":", 1)[1]
        if suffix == "manual":
            await q.answer()
            await state.set_state(ReminderTimeInput.waiting)
            return await q.message.edit_text(
                f"{e(self.emojis, 'reminders')} <b>Время уведомления</b>\n\n"
                "Введите время в формате <code>ЧЧ:ММ</code>, например <code>10:30</code>.",
                reply_markup=cancel_keyboard(self.emojis),
            )
        if len(suffix) != 4 or not suffix.isdigit():
            return await q.answer("Некорректное время", show_alert=True)
        value = f"{suffix[:2]}:{suffix[2:]}"
        try:
            self.db.set_payment_reminder_time(value)
        except ValueError as exc:
            return await q.answer(str(exc), show_alert=True)
        await self.reminders_page(q)

    async def reminder_time_input(self, m: Message, state: FSMContext):
        try:
            self.db.set_payment_reminder_time(str(m.text or "").strip())
        except ValueError as exc:
            return await m.answer(f"{e(self.emojis, 'warning')} {h(exc)}", reply_markup=cancel_keyboard(self.emojis))
        await state.clear()
        await m.answer(
            f"{e(self.emojis, 'paid')} Время уведомлений: <b>{h(self.db.payment_reminder_time())}</b>",
            reply_markup=reminder_keyboard(self.db.get_reminder_days(), self.db.overdue_daily(), self.db.payment_reminder_time(), self.emojis),
        )

    async def reports_page(self, q: CallbackQuery, state: FSMContext | None = None):
        if state:
            await state.clear()
        await q.answer()
        emojis = self.emojis
        enabled = self.db.monthly_report_enabled()
        day = self.db.report_day()
        hour = self.db.report_hour()
        minute = self.db.report_minute()
        text = (
            f"{e(emojis, 'reports')} <b>Отчёт</b>\n\n"
            f"Месячный отчёт: <b>{'включён' if enabled else 'выключен'}</b>\n"
            f"Когда придёт: <b>{day}-го числа в {hour:02d}:{minute:02d}</b>\n\n"
            "Выбери готовый день и время или введи их вручную."
        )
        await q.message.edit_text(text, reply_markup=reports_keyboard(enabled, day, hour, minute, emojis))

    async def report_toggle(self, q: CallbackQuery):
        self.db.set_setting("monthly_report_enabled", "0" if self.db.monthly_report_enabled() else "1")
        await self.reports_page(q)

    async def report_day(self, q: CallbackQuery, state: FSMContext):
        suffix = q.data.rsplit(":", 1)[1]
        if suffix == "manual":
            await q.answer()
            await state.set_state(ReportDayInput.waiting)
            return await q.message.edit_text(
                f"{e(self.emojis, 'reports')} <b>День отчёта</b>\n\nВведите число от <b>1</b> до <b>28</b>.",
                reply_markup=cancel_keyboard(self.emojis),
            )
        day = int(suffix)
        self.db.set_setting("report_day", str(max(1, min(28, day))))
        await self.reports_page(q)

    async def report_day_input(self, m: Message, state: FSMContext):
        try:
            day = int(str(m.text or "").strip())
        except ValueError:
            return await m.answer("Введите число от 1 до 28.", reply_markup=cancel_keyboard(self.emojis))
        if not 1 <= day <= 28:
            return await m.answer("Введите число от 1 до 28.", reply_markup=cancel_keyboard(self.emojis))
        self.db.set_setting("report_day", str(day))
        await state.clear()
        await m.answer(
            f"{e(self.emojis, 'paid')} День отчёта: <b>{day}</b>",
            reply_markup=reports_keyboard(self.db.monthly_report_enabled(), day, self.db.report_hour(), self.db.report_minute(), self.emojis),
        )

    async def report_time(self, q: CallbackQuery, state: FSMContext):
        suffix = q.data.rsplit(":", 1)[1]
        if suffix == "manual":
            await q.answer()
            await state.set_state(ReportTimeInput.waiting)
            return await q.message.edit_text(
                f"{e(self.emojis, 'reports')} <b>Время отчёта</b>\n\nВведите время в формате <code>ЧЧ:ММ</code>.",
                reply_markup=cancel_keyboard(self.emojis),
            )
        if len(suffix) != 4 or not suffix.isdigit():
            return await q.answer("Некорректное время", show_alert=True)
        value = f"{suffix[:2]}:{suffix[2:]}"
        try:
            self.db.set_report_time(value)
        except ValueError as exc:
            return await q.answer(str(exc), show_alert=True)
        await self.reports_page(q)

    async def report_time_input(self, m: Message, state: FSMContext):
        try:
            self.db.set_report_time(str(m.text or "").strip())
        except ValueError as exc:
            return await m.answer(f"{e(self.emojis, 'warning')} {h(exc)}", reply_markup=cancel_keyboard(self.emojis))
        await state.clear()
        await m.answer(
            f"{e(self.emojis, 'paid')} Время отчёта: <b>{self.db.report_hour():02d}:{self.db.report_minute():02d}</b>",
            reply_markup=reports_keyboard(self.db.monthly_report_enabled(), self.db.report_day(), self.db.report_hour(), self.db.report_minute(), self.emojis),
        )

    async def report_manual(self, q: CallbackQuery, state: FSMContext):
        await q.answer()
        await state.set_state(ReportScheduleInput.waiting)
        back = InlineKeyboardMarkup(inline_keyboard=[[
            button(self.emojis, "back", "Возврат", "settings:reports")
        ]])
        await q.message.edit_text(
            f"{e(self.emojis, 'reports')} <b>День и время отчёта</b>\n\n"
            "Введите день месяца и время через пробел.\n"
            "Например: <code>3 15:00</code>\n\n"
            "День: от <b>1</b> до <b>28</b>.",
            reply_markup=back,
        )

    async def report_manual_input(self, m: Message, state: FSMContext):
        raw = str(m.text or "").strip()
        parts = raw.split()
        if len(parts) != 2:
            return await m.answer("Введите в формате: <code>3 15:00</code>")
        try:
            day = int(parts[0])
        except ValueError:
            return await m.answer("День должен быть числом от 1 до 28.")
        if not 1 <= day <= 28:
            return await m.answer("День должен быть от 1 до 28.")
        try:
            self.db.set_report_time(parts[1])
        except ValueError as exc:
            return await m.answer(f"{e(self.emojis, 'warning')} {h(exc)}")
        self.db.set_setting("report_day", str(day))
        await state.clear()
        await m.answer(
            f"{e(self.emojis, 'paid')} Отчёт будет приходить <b>{day}-го числа в {self.db.report_hour():02d}:{self.db.report_minute():02d}</b>",
            reply_markup=reports_keyboard(
                self.db.monthly_report_enabled(),
                day,
                self.db.report_hour(),
                self.db.report_minute(),
                self.emojis,
            ),
        )

    async def report_default(self, q: CallbackQuery):
        self.db.set_setting("monthly_report_enabled", "1")
        self.db.set_setting("report_day", "1")
        self.db.set_report_time("10:00")
        await self.reports_page(q)

    async def emojis_page(self, q: CallbackQuery, state: FSMContext | None = None):
        if state:
            await state.clear()
        await q.answer()
        page = 0
        if q.data and str(q.data).startswith("emoji:page:"):
            try:
                page = int(str(q.data).rsplit(":", 1)[1])
            except ValueError:
                page = 0
        emojis = self.emojis
        text = (
            f"{e(emojis, 'emoji')} <b>Premium emoji</b>\n\n"
            "Нажми нужную иконку и отправь premium/custom emoji следующим сообщением. "
            "ID сохранится в базе и применится сразу, без рестарта.\n\n"
            "Если слот не переопределён - используется штатный premium emoji VPS Bill (если он задан), иначе Unicode."
        )
        await q.message.edit_text(text, reply_markup=emoji_keyboard(emojis, page))

    async def emoji_edit(self, q: CallbackQuery, state: FSMContext):
        parts = str(q.data or "").split(":")
        slot = parts[2] if len(parts) > 2 else ""
        page = 0
        if len(parts) >= 5 and parts[3] == "p":
            try:
                page = int(parts[4])
            except ValueError:
                page = 0
        if slot not in EMOJI_SLOTS:
            return await q.answer("Неизвестный слот", show_alert=True)
        await q.answer()
        await state.set_state(EmojiEdit.waiting)
        await state.update_data(emoji_slot=slot, emoji_page=page)
        emojis = self.emojis
        fallback, label = EMOJI_SLOTS[slot]
        current = emojis.get(slot)
        current_text = f"<code>{h(current)}</code>" if current else "штатный emoji VPS Bill / Unicode"
        await q.message.edit_text(
            f"{fallback} <b>{h(label)}</b>\n\n"
            f"Сейчас: {current_text}\n\n"
            "Отправь <b>один custom/premium emoji</b> следующим сообщением. "
            "Можно также прислать его numeric custom emoji ID.",
            reply_markup=emoji_edit_keyboard(slot, emojis, page),
        )

    async def emoji_input(self, m: Message, state: FSMContext):
        data = await state.get_data()
        slot = data.get("emoji_slot")
        page = int(data.get("emoji_page") or 0)
        if slot not in EMOJI_SLOTS:
            await state.clear()
            return await m.answer("Сессия настройки устарела. Открой Настройки → Справочники → Эмодзи ещё раз.")

        emoji_id: str | None = None
        for entity in m.entities or []:
            if entity.type == MessageEntityType.CUSTOM_EMOJI and entity.custom_emoji_id:
                emoji_id = entity.custom_emoji_id
                break
        if not emoji_id and (m.text or "").strip().isdigit():
            emoji_id = (m.text or "").strip()
        if not emoji_id:
            return await m.answer(
                f"{e(self.emojis, 'warning')} Не вижу custom emoji. Отправь именно premium/custom emoji или его numeric ID.",
                reply_markup=emoji_edit_keyboard(slot, self.emojis, page),
            )

        try:
            stickers = await m.bot.get_custom_emoji_stickers(custom_emoji_ids=[emoji_id])
            if not stickers:
                raise ValueError("ID не найден")
        except Exception as exc:
            return await m.answer(
                f"{e(self.emojis, 'warning')} Не удалось проверить этот custom emoji: <code>{h(str(exc)[:200])}</code>",
                reply_markup=emoji_edit_keyboard(slot, self.emojis, page),
            )

        self.db.set_emoji(slot, emoji_id)
        await state.clear()
        emojis = self.emojis
        await m.answer(
            f"{e(emojis, 'paid')} <b>Эмодзи сохранён</b>\n\nИзменение применено сразу.",
            reply_markup=emoji_keyboard(emojis, page),
        )

    async def emoji_reset(self, q: CallbackQuery, state: FSMContext):
        parts = str(q.data or "").split(":")
        slot = parts[2] if len(parts) > 2 else ""
        page = 0
        if len(parts) >= 5 and parts[3] == "p":
            try:
                page = int(parts[4])
            except ValueError:
                page = 0
        if slot in EMOJI_SLOTS:
            self.db.set_emoji(slot, "")
        await state.clear()
        await q.answer("Сброшено")
        emojis = self.emojis
        await q.message.edit_text("🎨 <b>Premium emoji</b>\n\nДля слота восстановлен emoji VPS Bill по умолчанию.", reply_markup=emoji_keyboard(emojis, page))

    async def emoji_cancel(self, q: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        page = int(data.get("emoji_page") or 0)
        await state.clear()
        await q.answer("Отменено")
        emojis = self.emojis
        await q.message.edit_text(f"{e(emojis, 'emoji')} <b>Premium emoji</b>", reply_markup=emoji_keyboard(emojis, page))

    async def emoji_resetall_ask(self, q: CallbackQuery):
        await q.answer()
        page = 0
        parts = str(q.data or "").split(":")
        if len(parts) >= 4 and parts[2] == "p":
            try:
                page = int(parts[3])
            except ValueError:
                page = 0
        emojis = self.emojis
        await q.message.edit_text(
            f"{e(emojis, 'warning')} <b>Сбросить все premium emoji?</b>\n\nВернётся штатный набор emoji VPS Bill по умолчанию.",
            reply_markup=kb([
                [button(emojis, "delete", "Да, сбросить все", f"emoji:resetall:yes:p:{page}", style="danger")],
                [button(emojis, "cancel", "Отмена", "settings:emojis", style="danger")],
            ]),
        )

    async def emoji_resetall_yes(self, q: CallbackQuery):
        parts = str(q.data or "").split(":")
        page = 0
        if len(parts) >= 5 and parts[3] == "p":
            try:
                page = int(parts[4])
            except ValueError:
                page = 0
        self.db.clear_all_emojis()
        await q.answer("Восстановлен набор по умолчанию")
        emojis = self.emojis
        await q.message.edit_text("🎨 <b>Premium emoji</b>\n\nВосстановлен штатный набор VPS Bill.", reply_markup=emoji_keyboard(emojis, page))

    async def monitoring_page(self, q: CallbackQuery):
        await q.answer()
        enabled = self.db.monitoring_enabled()
        interval = self.db.monitor_interval()
        failures = self.db.monitor_failures()
        recovery = self.db.monitor_recovery()
        method = self.db.monitor_method()
        tcp_port = self.db.monitor_tcp_port()
        all_state, total_with_ip, monitored = self.db.monitoring_all_state()
        method_label = {"auto": "Авто (Ping + TCP)", "ping": "Ping", "tcp": "TCP"}.get(method, "Авто (Ping + TCP)")
        text = (
            f"{e(self.emojis, 'monitor')} <b>Мониторинг</b>\n\n"
            f"Алерты: <b>{'включены' if enabled else 'выключены'}</b>\n"
            f"Серверов под наблюдением: <b>{monitored}</b>\n"
            f"Метод: <b>{method_label}</b>\n"
            f"TCP порт: <b>{tcp_port}</b>\n"
            f"Проверка: <b>каждые {interval // 60} мин.</b>\n"
            f"Считаем недоступным после: <b>{failures} ошибок подряд</b>\n"
            f"Восстановление после: <b>{recovery} успешных проверок</b>\n\n"
            "В режиме Авто сначала проверяется Ping. Если Ping не ответил - выполняется TCP-проверка."
        )
        await q.message.edit_text(
            text,
            reply_markup=monitoring_settings_keyboard(enabled, interval, failures, recovery, all_state, method, tcp_port, self.emojis),
        )

    async def monitor_global_toggle(self, q: CallbackQuery):
        enabling = not self.db.monitoring_enabled()
        self.db.set_setting("monitoring_enabled", "1" if enabling else "0")
        if enabling:
            # Predictable defaults every time global alerts are enabled.
            self.db.set_setting("monitor_interval", "180")
            self.db.set_setting("monitor_failures", "3")
            self.db.set_setting("monitor_recovery", "2")
        await self.monitoring_page(q)

    async def monitor_enable_all(self, q: CallbackQuery):
        was_enabled = self.db.monitoring_enabled()
        total, already = self.db.enable_monitoring_for_all_with_ip()
        self.db.set_setting("monitoring_enabled", "1")
        if not was_enabled:
            self.db.set_setting("monitor_interval", "180")
            self.db.set_setting("monitor_failures", "3")
            self.db.set_setting("monitor_recovery", "2")
        await self.monitoring_page(q)

    async def monitor_method_set(self, q: CallbackQuery):
        value = q.data.rsplit(":", 1)[1].strip().lower()
        if value not in {"auto", "ping", "tcp"}:
            return await q.answer("Недопустимый метод", show_alert=True)
        self.db.set_setting("monitor_method", value)
        await self.monitoring_page(q)

    async def monitor_tcp_port_start(self, q: CallbackQuery, state: FSMContext):
        await q.answer()
        await state.set_state(MonitorTcpPort.waiting)
        await q.message.edit_text(
            f"{e(self.emojis, 'monitor')} <b>TCP порт мониторинга</b>\n\n"
            f"Текущий порт: <b>{self.db.monitor_tcp_port()}</b>\n\n"
            "Отправь номер порта от 1 до 65535.",
            reply_markup=kb([[button(self.emojis, "back", "К мониторингу", "monitor:tcpport:cancel")]]),
        )

    async def monitor_tcp_port_cancel(self, q: CallbackQuery, state: FSMContext):
        await state.clear()
        await self.monitoring_page(q)

    async def monitor_tcp_port_input(self, m: Message, state: FSMContext):
        raw = str(m.text or "").strip()
        try:
            port = int(raw)
        except ValueError:
            return await m.answer("Введите номер порта от 1 до 65535.")
        if not 1 <= port <= 65535:
            return await m.answer("Введите номер порта от 1 до 65535.")
        self.db.set_setting("monitor_tcp_port", str(port))
        await state.clear()
        enabled = self.db.monitoring_enabled()
        interval = self.db.monitor_interval()
        failures = self.db.monitor_failures()
        recovery = self.db.monitor_recovery()
        method = self.db.monitor_method()
        all_state, _, monitored = self.db.monitoring_all_state()
        text = (
            f"{e(self.emojis, 'monitor')} <b>Мониторинг</b>\n\n"
            f"Алерты: <b>{'включены' if enabled else 'выключены'}</b>\n"
            f"Серверов под наблюдением: <b>{monitored}</b>\n"
            f"Метод: <b>{ {'auto': 'Авто (Ping + TCP)', 'ping': 'Ping', 'tcp': 'TCP'}.get(method, 'Авто (Ping + TCP)') }</b>\n"
            f"TCP порт: <b>{port}</b>\n"
            f"Проверка: <b>каждые {interval // 60} мин.</b>\n"
            f"Считаем недоступным после: <b>{failures} ошибок подряд</b>\n"
            f"Восстановление после: <b>{recovery} успешных проверок</b>\n\n"
            "В режиме Авто сначала проверяется Ping. Если Ping не ответил - выполняется TCP-проверка."
        )
        await m.answer(text, reply_markup=monitoring_settings_keyboard(enabled, interval, failures, recovery, all_state, method, port, self.emojis))

    async def monitor_interval_set(self, q: CallbackQuery):
        value = int(q.data.rsplit(":", 1)[1])
        if value not in {60, 180, 300, 600}:
            return await q.answer("Недопустимый интервал", show_alert=True)
        self.db.set_setting("monitor_interval", str(value))
        await self.monitoring_page(q)

    async def monitor_failures_set(self, q: CallbackQuery):
        value = int(q.data.rsplit(":", 1)[1])
        if value not in {2, 3, 5}:
            return await q.answer("Недопустимое значение", show_alert=True)
        self.db.set_setting("monitor_failures", str(value))
        await self.monitoring_page(q)

    async def monitor_recovery_set(self, q: CallbackQuery):
        value = int(q.data.rsplit(":", 1)[1])
        if value not in {1, 2, 3}:
            return await q.answer("Недопустимое значение", show_alert=True)
        self.db.set_setting("monitor_recovery", str(value))
        await self.monitoring_page(q)

    async def monitor_server_toggle(self, q: CallbackQuery):
        sid = int(q.data.rsplit(":", 1)[1])
        try:
            enabled = self.db.toggle_server_monitoring(sid)
        except ValueError as exc:
            return await q.answer(str(exc), show_alert=True)
        await q.answer("Мониторинг включён" if enabled else "Мониторинг выключен")
        server = self.db.get_server(sid)
        lines = [f"{e(self.emojis, 'edit')} <b>Данные VPS</b>", "", f"<b>{h(server['name'])}</b>"]
        fields = (("ip", "ip", "IP"), ("country", "country", "Страна"), ("tags", "tags", "Теги"), ("notes", "notes", "Заметка"))
        for key, slot, label in fields:
            value = str(server.get(key) or "").strip() or "-"
            if key == "tags" and value != "-":
                value = " · ".join(x.strip() for x in value.split(",") if x.strip())
            lines.append(f"{e(self.emojis, slot)} {label}: <b>{h(value)}</b>")
        lines.append(f"{e(self.emojis, 'monitor')} Мониторинг: <b>{'ВКЛ' if enabled else 'ВЫКЛ'}</b>")
        await q.message.edit_text("\n".join(lines), reply_markup=server_details_keyboard(sid, self.emojis, has_ip=True, has_country=bool(str(server.get("country") or "").strip()), has_tags=bool(str(server.get("tags") or "").strip()), has_notes=bool(str(server.get("notes") or "").strip()), monitor_enabled=enabled))

    def _cleanup_old_backups(self) -> tuple[int, int]:
        """Apply the configured age/count retention policy to local backups."""
        files = [
            p for p in self.settings.backups_dir.iterdir()
            if p.is_file() and p.name.startswith("vps-bill-")
            and (p.suffix == ".db" or p.name.endswith(".tar.gz"))
        ]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        cutoff = datetime.now().timestamp() - self.db.backup_keep_days() * 86400
        keep = self.db.backup_keep_count()
        removed = 0
        for idx, p in enumerate(files):
            if idx >= keep or p.stat().st_mtime < cutoff:
                try:
                    p.unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
        return removed, max(0, len(files) - removed)

    def _delete_old_backups(self) -> tuple[int, int, int]:
        return delete_old_backup_files(self.settings.backups_dir, days=30)

    async def backup_cleanup(self, q: CallbackQuery):
        removed, failed, freed_bytes = self._delete_old_backups()
        if failed:
            await q.answer(f"Удалено: {removed}, ошибок: {failed}", show_alert=True)
        elif removed:
            await q.answer(f"Удалено старых бекапов: {removed}")
        else:
            await q.answer("Старых бекапов нет")

        if freed_bytes >= 1024 ** 3:
            freed = f"{freed_bytes / (1024 ** 3):.1f} ГБ"
        elif freed_bytes >= 1024 ** 2:
            freed = f"{freed_bytes / (1024 ** 2):.1f} МБ"
        elif freed_bytes >= 1024:
            freed = f"{freed_bytes / 1024:.0f} КБ"
        else:
            freed = f"{freed_bytes} Б"

        text = (
            f"{e(self.emojis, 'backup')} <b>Бекап</b>\n\n"
            "Удаляются только бекапы старше <b>30 дней</b>. "
            "Более свежие резервные копии сохраняются.\n\n"
        )
        if removed:
            text += (
                f"Удалено: <b>{removed}</b>\n"
                f"Освобождено: <b>{freed}</b>"
            )
        else:
            text += "Старых бекапов нет."

        if failed:
            text += f"\nНе удалось удалить: <b>{failed}</b>"

        await q.message.edit_text(text, reply_markup=backups_keyboard(self.emojis))

    def _update_check_clock(self) -> str:
        hh, mm = (int(x) for x in self.db.payment_reminder_time().split(":", 1))
        base = datetime(2000, 1, 1, hh, mm) - timedelta(minutes=30)
        return base.strftime("%H:%M")

    @staticmethod
    def _release_notes_text(notes: str, limit: int = 3000) -> str:
        return changelog_to_telegram_html(notes, limit=limit)

    async def update_page(self, q: CallbackQuery):
        await q.answer()
        latest = None
        error = ""
        try:
            rel = await latest_release()
            if is_newer(rel.version, __version__):
                latest = rel.version
        except Exception as exc:
            error = str(exc)
        lines = [
            f"{e(self.emojis, 'update')} <b>Обновление</b>",
            "",
            f"Установлена: <b>{h(__version__)}</b>",
            f"Проверка: <b>ежедневно в {h(self._update_check_clock())}</b>",
            "Источник: <b>GitHub Releases</b>",
        ]
        if latest:
            lines += ["", f"Доступна: <b>{h(latest)}</b>"]
        elif error:
            lines += ["", f"Проверка сейчас не удалась: <code>{h(error[:180])}</code>"]
        else:
            lines += ["", "Установлена актуальная версия."]
        await q.message.edit_text("\n".join(lines), reply_markup=update_settings_keyboard(self.emojis, latest))

    async def update_check(self, q: CallbackQuery):
        await self.update_page(q)

    async def update_install(self, q: CallbackQuery):
        version = q.data.rsplit(":", 1)[1]
        await q.answer()
        try:
            rel = await latest_release()
        except Exception as exc:
            return await q.message.edit_text(
                f"{e(self.emojis, 'warning')} Не удалось проверить GitHub: <code>{h(str(exc)[:250])}</code>",
                reply_markup=update_settings_keyboard(self.emojis),
            )
        if rel.version != version or not is_newer(version, __version__):
            return await q.message.edit_text(
                "Версия уже не актуальна. Проверь обновления ещё раз.",
                reply_markup=update_settings_keyboard(self.emojis),
            )
        if not rel.asset_url:
            return await q.message.edit_text(
                f"В GitHub Release нет архива <code>vps-bill-{h(version)}.tar.gz</code>.",
                reply_markup=update_settings_keyboard(self.emojis),
            )
        text = (
            f"{e(self.emojis, 'update')} <b>Обновление VPS Bill</b>\n\n"
            f"{h(__version__)} → <b>{h(version)}</b>\n\n"
            "<b>Что изменилось:</b>\n"
            f"{self._release_notes_text(rel.notes)}\n\n"
            "Перед обновлением будет создан backup, миграция сначала проверится на копии БД. "
            "При ошибке штатный updater выполнит rollback."
        )
        await q.message.edit_text(text, reply_markup=update_confirm_keyboard(version), disable_web_page_preview=True)

    async def update_confirm(self, q: CallbackQuery):
        version = q.data.rsplit(":", 1)[1]
        await q.answer()
        try:
            rel = await latest_release()
            if rel.version != version or not is_newer(version, __version__) or not rel.asset_url:
                raise RuntimeError("релиз уже не является актуальным")
            request_id = create_update_request(self.settings.update_requests_dir, version)
        except Exception as exc:
            return await q.message.edit_text(
                f"{e(self.emojis, 'warning')} <b>Не удалось запустить обновление</b>\n\n<code>{h(str(exc))}</code>",
                reply_markup=update_settings_keyboard(self.emojis),
            )
        await q.message.edit_text(
            f"{e(self.emojis, 'update')} <b>Обновление запущено</b>\n\n"
            f"Версия: <b>{h(__version__)} → {h(version)}</b>\n"
            f"Заявка: <code>{h(request_id)}</code>\n\n"
            "Host-side updater скачает релиз с GitHub, создаст backup, проверит миграцию и перезапустит VPS Bill. "
            "После завершения бот сообщит результат.",
        )

    async def update_tomorrow(self, q: CallbackQuery):
        version = q.data.rsplit(":", 1)[1]
        tomorrow = (self.today + timedelta(days=1)).isoformat()
        self.db.set_update_last_offered(version)
        self.db.set_update_remind_after(tomorrow)
        await q.answer("Напомню завтра")
        await q.message.edit_reply_markup(reply_markup=None)

    async def update_ignore(self, q: CallbackQuery):
        version = q.data.rsplit(":", 1)[1]
        self.db.set_update_ignored_version(version)
        self.db.set_update_remind_after("")
        await q.answer("Эта версия больше не будет предлагаться")
        await q.message.edit_reply_markup(reply_markup=None)

    async def backups_page(self, q: CallbackQuery):
        await q.answer()
        self.settings.backups_dir.mkdir(parents=True, exist_ok=True)
        archives = sorted(self.settings.backups_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
        legacy = sorted(self.settings.backups_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        files = archives[:5] if archives else legacy[:5]
        lines = [
            f"{e(self.emojis, 'backup')} <b>Бекап</b>",
            "",
            f"Архивов: <b>{len(archives)}</b>",
            "",
            "«Удалить старые бекапы» удаляет только резервные копии старше <b>30 дней</b>.",
            "Более свежие бекапы сохраняются.",
        ]
        if files:
            lines += ["", "<b>Последние:</b>"]
            for file in files:
                size_kb = max(1, file.stat().st_size // 1024)
                lines.append(f"• <code>{h(file.name)}</code> · {size_kb} KB")
            if not archives and legacy:
                lines += ["", "Старые .db-бекапы продолжат работать; новые будут приходить архивом в Telegram."]
        else:
            lines += ["", "Бекапов пока нет."]
        await q.message.edit_text("\n".join(lines), reply_markup=backups_keyboard(self.emojis))

    async def backup(self, q: CallbackQuery):
        await q.answer("Создаю и отправляю бекап…")
        emojis = self.emojis
        try:
            raw, archive, _ = await self._create_and_send_backup(q.bot, q.from_user.id)
            self._cleanup_old_backups()
            await q.message.edit_text(
                f"{e(emojis, 'backup')} <b>Бекап готов</b>\n\n"
                f"Архив отправлен вам в Telegram.\n"
                f"Локально: <code>{h(archive.name)}</code>",
                reply_markup=backups_keyboard(emojis),
            )
        except Exception as exc:
            await q.message.edit_text(
                f"{e(emojis, 'warning')} <b>Бекап создать/отправить не удалось</b>\n\n<code>{h(exc)}</code>",
                reply_markup=backups_keyboard(emojis),
            )

    async def balance_topup_start(self, q: CallbackQuery, state: FSMContext):
        sid = int(q.data.rsplit(":", 1)[1])
        server = self.db.get_server(sid)
        if not server or str(server.get("billing_mode") or "") != "balance":
            return await q.answer("Балансовый режим не включён", show_alert=True)
        await state.set_state(BalanceTopup.waiting)
        await state.update_data(balance_topup_server_id=sid)
        await q.answer()
        await q.message.edit_text(
            f"{e(self.emojis, 'payments')} <b>Пополнение баланса</b>\n\nВведите сумму пополнения. Она сразу попадёт в расходы текущего месяца.",
            reply_markup=cancel_keyboard(self.emojis),
        )

    async def balance_topup_input(self, m: Message, state: FSMContext):
        try:
            amount = parse_amount_minor(m.text or "")
        except ValueError as exc:
            return await m.answer(f"{e(self.emojis, 'warning')} {h(exc)}. Введите сумму ещё раз:", reply_markup=cancel_keyboard(self.emojis))
        data = await state.get_data()
        sid = int(data.get("balance_topup_server_id") or 0)
        if not sid:
            await state.clear()
            return await m.answer("Сессия устарела.", reply_markup=main_menu(self.emojis))
        new_balance = self.db.topup_balance(sid, amount)
        await state.clear()
        server = self.db.get_server(sid)
        await m.answer(
            f"{e(self.emojis, 'paid')} <b>Баланс пополнен</b>\n\nДобавлено: <b>{money(amount, server['currency'])}</b>\nТекущий расчётный баланс: <b>{money(new_balance, server['currency'])}</b>\n\n" + server_card(server, self.emojis),
            reply_markup=server_buttons(sid, self.emojis, balance_mode=True),
        )

    async def paid(self, q: CallbackQuery):
        parts = q.data.split(":", 2)
        sid = int(parts[1])
        expected_due_from_button = parts[2] if len(parts) > 2 and parts[2] else None
        s = self.db.get_server(sid)
        if not s:
            return await q.answer("Сервер не найден", show_alert=True)
        if str(s.get("billing_mode") or "") == "balance":
            return await q.answer("Для этого VPS используется пополнение баланса", show_alert=True)
        expected_due = expected_due_from_button or str(s["next_due"])
        # A reminder button belongs to one exact billing period. Old/stale buttons
        # must never pay the following period.
        if expected_due_from_button and str(s["next_due"]) != expected_due_from_button:
            return await q.answer("Этот платёж уже обработан", show_alert=True)
        nd = next_due(expected_due, s["cycle"], s["cycle_days"])
        paid, current = self.db.add_payment_atomic(
            sid, expected_due, s["amount_minor"], s["currency"], nd
        )
        if not paid:
            return await q.answer("Этот платёж уже обработан", show_alert=True)
        await q.answer("Оплачено ✅")
        emojis = self.emojis
        await q.message.edit_text(
            f"{e(emojis, 'paid')} <b>Оплачено</b>\n\n"
            f"<b>{h(s['name'])}</b> · {money(s['amount_minor'], s['currency'])}\n"
            f"Следующая оплата: <b>{date.fromisoformat(nd).strftime('%d.%m.%y')}</b>\n\n"
            + self._main_text(),
            reply_markup=main_menu(emojis),
        )

    async def snooze(self, q: CallbackQuery):
        sid = int(q.data.split(":", 1)[1])
        until = datetime.now(ZoneInfo(self.settings.timezone)) + timedelta(days=1)
        until = until.replace(hour=9, minute=0, second=0, microsecond=0)
        self.db.snooze_until(sid, until.isoformat())
        await q.answer("Напомню завтра")

    async def server_details(self, q: CallbackQuery):
        sid = int(q.data.split(":", 1)[1])
        server = self.db.get_server(sid)
        await q.answer()
        if not server or server.get("deleted_at"):
            return await q.message.edit_text("Сервер не найден.", reply_markup=back_main(self.emojis))
        lines = [f"{e(self.emojis, 'edit')} <b>Данные VPS</b>", "", f"<b>{h(server['name'])}</b>"]
        fields = (
            ("ip", "ip", "IP"),
            ("country", "country", "Страна"),
            ("tags", "tags", "Теги"),
            ("notes", "notes", "Заметка"),
        )
        for key, slot, label in fields:
            value = str(server.get(key) or "").strip() or "-"
            if key == "tags" and value != "-":
                value = " · ".join(x.strip() for x in value.split(",") if x.strip())
            lines.append(f"{e(self.emojis, slot)} {label}: <b>{h(value)}</b>")
        await q.message.edit_text("\n".join(lines), reply_markup=server_details_keyboard(sid, self.emojis, has_ip=bool(str(server.get("ip") or "").strip()), has_country=bool(str(server.get("country") or "").strip()), has_tags=bool(str(server.get("tags") or "").strip()), has_notes=bool(str(server.get("notes") or "").strip()), monitor_enabled=bool(server.get("monitor_enabled"))))

    async def country_choose(self, q: CallbackQuery):
        sid = int(q.data.rsplit(":", 1)[1])
        server = self.db.get_server(sid)
        if not server or server.get("deleted_at"):
            return await q.answer("Сервер не найден", show_alert=True)
        countries = self.db.used_countries()
        await q.answer()
        text = f"{e(self.emojis, 'country')} <b>Страна сервера</b>\n\n"
        if countries:
            text += "Выбери из уже использованных или добавь новую."
        else:
            text += "Сохранённых стран пока нет. Добавь первую страну."
        await q.message.edit_text(text, reply_markup=country_picker_keyboard(sid, countries, self.emojis))

    async def country_set(self, q: CallbackQuery):
        parts = q.data.split(":")
        if len(parts) != 4:
            return await q.answer("Некорректный выбор", show_alert=True)
        sid = int(parts[2])
        idx = int(parts[3])
        countries = self.db.used_countries()[:24]
        if idx < 0 or idx >= len(countries):
            return await q.answer("Список стран изменился. Открой выбор ещё раз.", show_alert=True)
        self.db.update_server_field(sid, "country", countries[idx])
        await q.answer("Страна сохранена")
        server = self.db.get_server(sid)
        await q.message.edit_text(
            f"{e(self.emojis, 'paid')} <b>Сохранено</b>\n\n" + server_card(server, self.emojis),
            reply_markup=server_buttons(sid, self.emojis, balance_mode=str(server.get("billing_mode") or "") == "balance"),
        )

    async def tag_choose(self, q: CallbackQuery):
        sid = int(q.data.rsplit(":", 1)[1])
        server = self.db.get_server(sid)
        if not server or server.get("deleted_at"):
            return await q.answer("Сервер не найден", show_alert=True)
        all_tags = self.db.used_tags()
        active = [x.strip() for x in str(server.get("tags") or "").split(",") if x.strip()]
        await q.answer()
        text = f"{e(self.emojis, 'tags')} <b>Теги сервера</b>\n\nНажимай на теги, чтобы добавить или убрать их."
        await q.message.edit_text(text, reply_markup=tag_picker_keyboard(sid, all_tags, active, self.emojis))

    async def tag_toggle(self, q: CallbackQuery):
        parts = q.data.split(":")
        sid = int(parts[2]); idx = int(parts[3])
        tags = self.db.used_tags()[:30]
        if idx < 0 or idx >= len(tags):
            return await q.answer("Список тегов изменился. Открой ещё раз.", show_alert=True)
        active = self.db.toggle_server_tag(sid, tags[idx])
        await q.answer("Тег добавлен" if active else "Тег убран")
        server = self.db.get_server(sid)
        current = [x.strip() for x in str(server.get("tags") or "").split(",") if x.strip()]
        await q.message.edit_reply_markup(reply_markup=tag_picker_keyboard(sid, self.db.used_tags(), current, self.emojis))

    async def tag_new(self, q: CallbackQuery, state: FSMContext):
        sid = int(q.data.rsplit(":", 1)[1])
        if not self.db.get_server(sid):
            return await q.answer("Сервер не найден", show_alert=True)
        await state.set_state(EditServerField.waiting)
        await state.update_data(edit_server_id=sid, edit_server_field="tag_add")
        await q.answer()
        await q.message.edit_text(f"{e(self.emojis, 'tags')} Введите новый тег:", reply_markup=cancel_keyboard(self.emojis))

    async def edit_server_field(self, q: CallbackQuery, state: FSMContext):
        _, sid_raw, field = q.data.split(":", 2)
        sid = int(sid_raw)
        labels = {
            "name": "новое имя сервера",
            "ip": "IP",
            "country": "страну",
            "tags": "теги через запятую",
            "notes": "заметку",
        }
        if field not in labels or not self.db.get_server(sid):
            return await q.answer("Поле недоступно", show_alert=True)
        await state.set_state(EditServerField.waiting)
        await state.update_data(edit_server_id=sid, edit_server_field=field)
        await q.answer()
        prompt = f"{e(self.emojis, 'edit')} Введите {labels[field]}."
        if field != "name":
            prompt += "\n\nДля очистки поля отправьте: <code>-</code>"
        await q.message.edit_text(
            prompt,
            reply_markup=server_edit_back_keyboard(sid, self.emojis),
        )

    async def edit_server_back(self, q: CallbackQuery, state: FSMContext):
        sid = int(q.data.split(":", 1)[1])
        await state.clear()
        server = self.db.get_server(sid)
        await q.answer()
        if not server or server.get("deleted_at"):
            return await q.message.edit_text("Сервер не найден.", reply_markup=back_main(self.emojis))
        await q.message.edit_text(
            server_card(server, self.emojis),
            reply_markup=server_buttons(
                sid,
                self.emojis,
                balance_mode=str(server.get("billing_mode") or "") == "balance",
            ),
        )

    async def edit_server_field_input(self, m: Message, state: FSMContext):
        data = await state.get_data()
        sid = int(data.get("edit_server_id", 0) or 0)
        field = str(data.get("edit_server_field") or "")
        if not sid or field not in {"name", "ip", "country", "tags", "notes", "tag_add"}:
            await state.clear()
            return await m.answer("Сессия редактирования устарела.", reply_markup=main_menu(self.emojis))
        value = (m.text or "").strip()
        if not value:
            message = "Введите новое имя сервера." if field == "name" else "Введите значение или <code>-</code> для очистки."
            return await m.answer(message, reply_markup=server_edit_back_keyboard(sid, self.emojis))
        if field == "name":
            value = " ".join(value.split())[:128]
            if value == "-":
                return await m.answer("Имя сервера нельзя очистить. Введите новое имя.", reply_markup=server_edit_back_keyboard(sid, self.emojis))
        elif value == "-":
            value = ""
        if field == "tag_add":
            self.db.add_server_tag(sid, value)
        else:
            self.db.update_server_field(sid, field, value)
        await state.clear()
        server = self.db.get_server(sid)
        await m.answer(
            f"{e(self.emojis, 'paid')} <b>Сохранено</b>\n\n" + server_card(server, self.emojis),
            reply_markup=server_buttons(sid, self.emojis, balance_mode=str(server.get("billing_mode") or "") == "balance"),
        )

    async def archive_ask(self, q: CallbackQuery):
        await q.answer()
        sid=int(q.data.split(":",1)[1]); srv=self.db.get_server(sid)
        if not srv: return
        await q.message.edit_text(f"{e(self.emojis, 'server')} <b>Переместить в архив?</b>\n\n{h(srv['name'])}\n\nИстория платежей сохранится в аналитике.", reply_markup=kb([[button(self.emojis,"server","В архив",f"archiveyes:{sid}",style="success")],[button(self.emojis,"cancel","Отмена",f"srvopen:{sid}")]]))

    async def archive_yes(self, q: CallbackQuery):
        sid=int(q.data.split(":",1)[1]); self.db.archive_server(sid); await q.answer("Перемещено в архив")
        items=self.db.list_archive(); await q.message.edit_text(f"{e(self.emojis, 'server')} <b>Архив</b>\n\nСерверов: <b>{len(items)}</b>", reply_markup=archive_list_keyboard(items,self.emojis))

    async def archive_page(self, q: CallbackQuery):
        await q.answer(); items=self.db.list_archive(); page=0
        if q.data and q.data.startswith("archive:page:"):
            try: page=int(q.data.rsplit(":",1)[1])
            except ValueError: page=0
        await q.message.edit_text(f"{e(self.emojis, 'server')} <b>Архив VPS</b>\n\nСерверов: <b>{len(items)}</b>\nИстория оплат сохранена и продолжает учитываться в фактических расходах.", reply_markup=archive_list_keyboard(items,self.emojis,page=page))

    async def archive_item(self, q: CallbackQuery):
        await q.answer(); sid=int(q.data.split(":",1)[1]); srv=self.db.get_server(sid)
        if not srv: return await self.archive_page(q)
        await q.message.edit_text(server_card(srv,self.emojis), reply_markup=archive_item_keyboard(sid,self.emojis))

    async def archive_restore(self, q: CallbackQuery):
        sid=int(q.data.split(":",1)[1]); self.db.restore_archived_server(sid); await q.answer("Возвращён в активные")
        await q.message.edit_text(server_card(self.db.get_server(sid),self.emojis), reply_markup=server_buttons(sid,self.emojis,balance_mode=str(self.db.get_server(sid).get("billing_mode") or "")=="balance"))

    async def archive_to_trash(self, q: CallbackQuery):
        sid=int(q.data.split(":",1)[1]); self.db.archive_to_trash(sid); await q.answer("Перемещено в корзину")
        items=self.db.list_archive(); await q.message.edit_text(f"{e(self.emojis, 'server')} <b>Архив VPS</b>\n\nСерверов: <b>{len(items)}</b>", reply_markup=archive_list_keyboard(items,self.emojis))

    async def trash_ask(self, q: CallbackQuery):
        sid = int(q.data.split(":", 1)[1])
        server = self.db.get_server(sid)
        await q.answer()
        if not server:
            return
        await q.message.edit_text(
            f"{e(self.emojis, 'trash')} <b>Переместить в корзину?</b>\n\n"
            f"<b>{h(server['name'])}</b> перестанет участвовать в напоминаниях и аналитике. История оплат сохранится.",
            reply_markup=kb([
                [button(self.emojis, "trash", "В корзину", f"trashyes:{sid}", style="danger")],
                [button(self.emojis, "cancel", "Отмена", f"srvopen:{sid}", style="primary")],
            ]),
        )

    async def trash_yes(self, q: CallbackQuery):
        sid = int(q.data.split(":", 1)[1])
        self.db.trash_server(sid)
        await q.answer("Перемещено в корзину")
        await q.message.edit_text(self._main_text(), reply_markup=main_menu(self.emojis))

    async def trash_page(self, q: CallbackQuery):
        await q.answer()
        items = self.db.list_trash()
        page = 0
        page_size = 8
        if q.data and q.data.startswith("trash:page:"):
            try:
                page = int(q.data.rsplit(":", 1)[1])
            except ValueError:
                page = 0
        total_pages = max(1, (len(items) + page_size - 1) // page_size)
        page = max(0, min(page, total_pages - 1))
        text = f"{e(self.emojis, 'trash')} <b>Корзина</b>\n\n"
        text += f"Серверов: <b>{len(items)}</b>" if items else "Корзина пуста."
        if total_pages > 1:
            text += f"\nСтраница: <b>{page + 1}/{total_pages}</b>"
        await q.message.edit_text(text, reply_markup=trash_list_keyboard(items, self.emojis, page=page, page_size=page_size))

    async def trash_item(self, q: CallbackQuery):
        sid = int(q.data.split(":", 1)[1])
        server = self.db.get_server(sid)
        await q.answer()
        if not server or not server.get("deleted_at"):
            items = self.db.list_trash()
            return await q.message.edit_text(
                f"{e(self.emojis, 'trash')} <b>Корзина</b>",
                reply_markup=trash_list_keyboard(items, self.emojis),
            )
        await q.message.edit_text(server_card(server, self.emojis), reply_markup=trash_item_keyboard(sid, self.emojis))

    async def restore_server(self, q: CallbackQuery):
        sid = int(q.data.split(":", 1)[1])
        self.db.restore_server(sid)
        await q.answer("Восстановлено ✅")
        server = self.db.get_server(sid)
        await q.message.edit_text(server_card(server, self.emojis), reply_markup=server_buttons(sid, self.emojis, balance_mode=str(server.get("billing_mode") or "") == "balance"))

    async def purge_ask(self, q: CallbackQuery):
        sid = int(q.data.split(":", 1)[1])
        server = self.db.get_server(sid)
        await q.answer()
        if not server or not server.get("deleted_at"):
            return
        await q.message.edit_text(
            f"{e(self.emojis, 'purge')} <b>Удалить навсегда?</b>\n\n"
            f"<b>{h(server['name'])}</b> и история его оплат будут удалены без возможности восстановления.",
            reply_markup=kb([
                [button(self.emojis, "purge", "Удалить навсегда", f"purgeyes:{sid}", style="danger")],
                [button(self.emojis, "cancel", "Отмена", f"trashitem:{sid}", style="primary")],
            ]),
        )

    async def purge_yes(self, q: CallbackQuery):
        sid = int(q.data.split(":", 1)[1])
        server = self.db.get_server(sid)
        if not server or not server.get("deleted_at"):
            return await q.answer("Сервер не найден в корзине", show_alert=True)

        self.db.purge_server(sid)
        await q.answer("Удалено навсегда", show_alert=True)
        items = self.db.list_trash()
        await q.message.edit_text(
            f"{e(self.emojis, 'trash')} <b>Корзина</b>\n\n"
            f"Сервер <b>{h(server['name'])}</b> удалён навсегда.",
            reply_markup=trash_list_keyboard(items, self.emojis),
        )

    async def purge_all_ask(self, q: CallbackQuery):
        items = self.db.list_trash()
        await q.answer()
        if not items:
            return await q.message.edit_text(
                f"{e(self.emojis, 'trash')} <b>Корзина</b>\n\nКорзина пуста.",
                reply_markup=trash_list_keyboard([], self.emojis),
            )
        await q.message.edit_text(
            f"{e(self.emojis, 'purge')} <b>Удалить всю корзину навсегда?</b>\n\n"
            f"Будут удалены <b>{len(items)}</b> серверов вместе с историей их оплат.\n\n"
            f"Перед удалением бот создаст backup всей базы и пришлёт архив в Telegram.",
            reply_markup=kb([
                [button(self.emojis, "purge", "Удалить все навсегда", "trash:purgeall:yes", style="danger")],
                [button(self.emojis, "cancel", "Отмена", "trash")],
            ]),
        )

    async def purge_all_yes(self, q: CallbackQuery):
        items = self.db.list_trash()
        if not items:
            await q.answer("Корзина уже пуста", show_alert=True)
            return await q.message.edit_text(
                f"{e(self.emojis, 'trash')} <b>Корзина</b>\n\nКорзина пуста.",
                reply_markup=trash_list_keyboard([], self.emojis),
            )

        try:
            _, archive, _ = await self._create_and_send_backup(
                q.bot,
                q.from_user.id,
                prefix="vps-bill-pre-purge-all",
                caption=(
                    f"{e(self.emojis, 'backup')} <b>Backup перед очисткой корзины</b>\n\n"
                    f"Серверов в корзине: <b>{len(items)}</b>\n"
                    f"После отправки этого архива корзина будет очищена навсегда."
                ),
            )
        except Exception as exc:
            await q.answer("Удаление отменено: backup не отправлен", show_alert=True)
            return await q.message.edit_text(
                f"{e(self.emojis, 'warning')} <b>Удаление отменено</b>\n\n"
                f"Не удалось создать или отправить backup:\n<code>{h(exc)}</code>",
                reply_markup=trash_list_keyboard(items, self.emojis),
            )

        count = self.db.purge_all_trash()
        await q.answer(f"Удалено серверов: {count}", show_alert=True)
        await q.message.edit_text(
            f"{e(self.emojis, 'trash')} <b>Корзина</b>\n\n"
            f"Удалено навсегда: <b>{count}</b>\n"
            f"Backup: <code>{h(archive.name)}</code>",
            reply_markup=trash_list_keyboard([], self.emojis),
        )

    async def add_start(self, q: CallbackQuery, state: FSMContext):
        await q.answer()
        await state.clear()
        await state.set_state(AddServer.name)
        emojis = self.emojis
        await q.message.edit_text(
            f"{e(emojis, 'add')} <b>Новый VPS</b>\n\nВведите название сервера:\nНапример: <code>rw-node-fi4</code>",
            reply_markup=cancel_keyboard(emojis),
        )

    async def add_name(self, m: Message, state: FSMContext):
        if not m.text or not m.text.strip():
            return
        await state.update_data(name=m.text.strip())
        providers = self.db.list_providers()[:20]
        await state.update_data(provider_choices=providers)
        await state.set_state(AddServer.provider)
        emojis = self.emojis
        text = f"{e(emojis, 'provider')} <b>Выберите хостера</b>"
        if not providers:
            text += "\n\nСуществующих хостеров пока нет - добавьте первого."
        await m.answer(text, reply_markup=provider_keyboard(providers, emojis))

    async def _ask_cycle(self, target, provider: str, state: FSMContext):
        await state.update_data(provider=provider)
        await state.set_state(AddServer.cycle)
        await target.answer(
            f"{e(self.emojis, 'provider')} Хостер: <b>{h(provider)}</b>\n\n<b>Период оплаты:</b>",
            reply_markup=cycle_keyboard(self.emojis, self.db.get_billing_cycles()),
        )

    async def add_provider_select(self, q: CallbackQuery, state: FSMContext):
        idx = int(q.data.rsplit(":", 1)[1])
        data = await state.get_data()
        choices = data.get("provider_choices", [])
        if idx < 0 or idx >= len(choices):
            return await q.answer("Список изменился, выберите ещё раз", show_alert=True)
        provider = str(choices[idx])
        await q.answer(provider)
        await state.update_data(provider=provider)
        await state.set_state(AddServer.cycle)
        await q.message.edit_text(
            f"{e(self.emojis, 'provider')} Хостер: <b>{h(provider)}</b>\n\n<b>Период оплаты:</b>",
            reply_markup=cycle_keyboard(self.emojis, self.db.get_billing_cycles()),
        )

    async def add_provider_new(self, q: CallbackQuery, state: FSMContext):
        await q.answer()
        await q.message.edit_text(
            f"{e(self.emojis, 'provider')} <b>Новый хостер</b>\n\nВведите название, например: <code>Hetzner</code>",
            reply_markup=cancel_keyboard(self.emojis),
        )

    async def add_provider(self, m: Message, state: FSMContext):
        if not m.text or not m.text.strip():
            return
        provider = m.text.strip()
        await state.update_data(provider=provider)
        await state.set_state(AddServer.cycle)
        await m.answer(
            f"{e(self.emojis, 'provider')} Хостер: <b>{h(provider)}</b>\n\n<b>Период оплаты:</b>",
            reply_markup=cycle_keyboard(self.emojis, self.db.get_billing_cycles()),
        )

    async def add_cycle(self, q: CallbackQuery, state: FSMContext):
        cycle = q.data.split(":", 1)[1]
        if cycle not in set(self.db.get_billing_cycles()):
            return await q.answer("Неизвестный период", show_alert=True)
        await state.update_data(cycle=cycle)
        await q.answer()
        if cycle == "daily":
            await state.set_state(AddServer.daily_mode)
            await q.message.edit_text(
                f"{e(self.emojis, 'cycle')} <b>Ежедневная оплата</b>\n\nКак оплачивается сервер?",
                reply_markup=daily_mode_keyboard(self.emojis),
            )
            return
        await state.update_data(billing_mode="scheduled")
        await state.set_state(AddServer.currency)
        currencies = self.db.active_currency_codes()
        await q.message.edit_text(
            f"{e(self.emojis, 'money')} <b>Валюта</b>",
            reply_markup=currency_keyboard(self.emojis, currencies),
        )

    async def add_daily_mode(self, q: CallbackQuery, state: FSMContext):
        mode = q.data.split(":", 1)[1]
        if mode not in {"manual", "balance"}:
            return await q.answer("Неизвестный режим", show_alert=True)
        await state.update_data(billing_mode="balance" if mode == "balance" else "scheduled")
        await state.set_state(AddServer.currency)
        await q.answer()
        await q.message.edit_text(
            f"{e(self.emojis, 'money')} <b>Валюта</b>",
            reply_markup=currency_keyboard(self.emojis, self.db.active_currency_codes()),
        )

    async def add_currency(self, q: CallbackQuery, state: FSMContext):
        currency = q.data.split(":", 1)[1].upper()
        if currency not in set(self.db.active_currency_codes()):
            return await q.answer("Эта валюта сейчас выключена", show_alert=True)
        await q.answer(currency)
        await state.update_data(currency=currency)
        await state.set_state(AddServer.amount)
        await q.message.edit_text(
            f"{e(self.emojis, 'money')} Валюта: <b>{h(currency)}</b>\n\nВведите сумму за выбранный период:\nНапример: <code>15.90</code>",
            reply_markup=cancel_keyboard(self.emojis),
        )

    async def add_amount(self, m: Message, state: FSMContext):
        try:
            amount = parse_amount_minor(m.text or "")
        except ValueError as exc:
            return await m.answer(
                f"{e(self.emojis, 'warning')} {h(exc)}. Введите сумму ещё раз:",
                reply_markup=cancel_keyboard(self.emojis),
            )
        await state.update_data(amount_minor=amount)
        data = await state.get_data()
        if data.get("billing_mode") == "balance":
            await state.set_state(AddServer.balance)
            await m.answer(
                f"{e(self.emojis, 'payments')} <b>Текущий баланс у хостера</b>\n\nВведите остаток на балансе в выбранной валюте:",
                reply_markup=cancel_keyboard(self.emojis),
            )
            return
        await state.set_state(AddServer.due)
        today = self.today
        await m.answer(
            f"{e(self.emojis, 'calendar')} <b>Следующая дата платежа</b>\n\nВыберите день:",
            reply_markup=calendar_keyboard(self.emojis, today.year, today.month, "add", today=today),
        )

    async def add_balance(self, m: Message, state: FSMContext):
        try:
            balance = parse_amount_minor(m.text or "")
        except ValueError as exc:
            return await m.answer(f"{e(self.emojis, 'warning')} {h(exc)}. Введите баланс ещё раз:", reply_markup=cancel_keyboard(self.emojis))
        await state.update_data(balance_minor=balance)
        await state.set_state(AddServer.balance_alert)
        await m.answer(
            f"{e(self.emojis, 'reminders')} <b>Когда предупредить о заканчивающемся балансе?</b>\n\nВыбери, на сколько дней работы должен остаться баланс:",
            reply_markup=balance_alert_keyboard(self.emojis),
        )

    async def add_balance_alert(self, q: CallbackQuery, state: FSMContext):
        days = int(q.data.rsplit(":", 1)[1])
        if days not in {1, 3, 7}:
            return await q.answer("Некорректный порог", show_alert=True)
        data = await state.get_data()
        amount = int(data["amount_minor"])
        balance = int(data.get("balance_minor") or 0)
        estimated_days = balance // max(1, amount)
        next_due = (self.today + timedelta(days=max(0, estimated_days))).isoformat()
        sid = self.db.add_server(
            name=data["name"], provider=data["provider"], amount_minor=amount, currency=data["currency"],
            next_due=next_due, cycle="daily", billing_mode="balance", balance_minor=balance, balance_alert_days=days,
        )
        await state.clear()
        await q.answer("VPS добавлен")
        s = self.db.get_server(sid)
        monitor_hint = "\n\n📡 <b>Нужен мониторинг доступности?</b>\nДобавь IP в <b>Данные - IP</b>, после этого можно включить мониторинг сервера."
        await q.message.edit_text(
            f"{e(self.emojis, 'paid')} <b>VPS добавлен</b>\n\n" + server_card(s, self.emojis) + monitor_hint,
            reply_markup=server_buttons(sid, self.emojis, balance_mode=True),
        )

    async def calendar_nav_add(self, q: CallbackQuery):
        ym = q.data.rsplit(":", 1)[1]
        year, month = [int(x) for x in ym.split("-")]
        await q.answer()
        await q.message.edit_reply_markup(reply_markup=calendar_keyboard(self.emojis, year, month, "add", today=self.today))

    async def calendar_day_add(self, q: CallbackQuery, state: FSMContext):
        raw = q.data.rsplit(":", 1)[1]
        selected = date.fromisoformat(raw)
        await state.update_data(next_due=selected.isoformat())
        await state.set_state(AddServer.record_current)
        await q.answer(selected.strftime("%d.%m.%y"))
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        await q.message.edit_text(
            f"{e(self.emojis, 'calendar')} Следующая оплата: <b>{selected.strftime('%d.%m.%y')}</b>\n\n"
            f"{e(self.emojis, 'payments')} <b>Записать платёж за текущий месяц в траты?</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Да, записать", callback_data="addpay:yes", style="success")],
                [InlineKeyboardButton(text="Нет", callback_data="addpay:no")],
                [button(self.emojis, "cancel", "Отмена", "flow:cancel", style="danger")],
            ]),
        )

    async def add_record_current(self, q: CallbackQuery, state: FSMContext):
        record = q.data == "addpay:yes"
        data = await state.get_data()
        sid = self.db.add_server(
            name=data["name"],
            provider=data["provider"],
            amount_minor=data["amount_minor"],
            currency=data["currency"],
            next_due=data["next_due"],
            cycle=data["cycle"],
            billing_mode=data.get("billing_mode", "scheduled"),
        )
        if record:
            self.db.record_payment_only(
                sid,
                data["amount_minor"],
                data["currency"],
                self.today.isoformat(),
                note="Платёж за текущий месяц при добавлении VPS",
            )
        await state.clear()
        await q.answer("VPS добавлен")
        s = self.db.get_server(sid)
        suffix = "\n\n✅ Платёж добавлен в траты этого месяца." if record else ""
        monitor_hint = (
            "\n\n📡 <b>Нужен мониторинг доступности?</b>\n"
            "Добавь IP в <b>Данные - IP</b>, после этого можно включить мониторинг сервера."
        )
        await q.message.edit_text(
            f"{e(self.emojis, 'paid')} <b>VPS добавлен</b>\n\n" + server_card(s, self.emojis) + suffix + monitor_hint,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [button(self.emojis, "back", "К карточке", f"srvopen:{sid}")],
            ]),
        )

    async def change_date_start(self, q: CallbackQuery, state: FSMContext):
        sid = int(q.data.split(":", 1)[1])
        s = self.db.get_server(sid)
        if not s:
            return await q.answer("Сервер не найден", show_alert=True)
        current = date.fromisoformat(s["next_due"])
        await q.answer()
        await state.set_state(ChangeDate.due)
        await state.update_data(server_id=sid)
        await q.message.edit_text(
            f"{e(self.emojis, 'calendar')} <b>Изменить дату оплаты</b>\n\nТекущая: <b>{current.strftime('%d.%m.%y')}</b>",
            reply_markup=calendar_keyboard(self.emojis, current.year, current.month, "date", today=self.today),
        )

    async def calendar_nav_date(self, q: CallbackQuery):
        ym = q.data.rsplit(":", 1)[1]
        year, month = [int(x) for x in ym.split("-")]
        await q.answer()
        await q.message.edit_reply_markup(reply_markup=calendar_keyboard(self.emojis, year, month, "date", today=self.today))

    async def calendar_day_date(self, q: CallbackQuery, state: FSMContext):
        selected = date.fromisoformat(q.data.rsplit(":", 1)[1])
        data = await state.get_data()
        sid = int(data["server_id"])
        self.db.update_due(sid, selected.isoformat())
        await state.clear()
        await q.answer("Дата изменена")
        s = self.db.get_server(sid)
        emojis = self.emojis
        await q.message.edit_text(
            f"{e(emojis, 'paid')} <b>Дата изменена</b>\n\n" + server_card(s, emojis),
            reply_markup=server_buttons(sid, emojis, balance_mode=str(s.get("billing_mode") or "") == "balance"),
        )
