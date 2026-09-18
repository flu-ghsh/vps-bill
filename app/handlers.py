from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .billing import money, next_due, parse_amount_minor, parse_date, sum_by_currency
from .config import Settings, mask_proxy
from .db import Database
from .ui import back_main, h, main_menu, notification_buttons, server_buttons, server_card


class AddServer(StatesGroup):
    name = State(); provider = State(); amount = State(); currency = State(); due = State(); cycle = State()


class ChangeDate(StatesGroup):
    due = State()


def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


class BotHandlers:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.router = Router()
        self._register()

    @property
    def today(self) -> date:
        return datetime.now(ZoneInfo(self.settings.timezone)).date()

    def _main_text(self) -> str:
        servers = self.db.list_servers()
        overdue = [s for s in servers if date.fromisoformat(s["next_due"]) < self.today]
        soon = [s for s in servers if 0 <= (date.fromisoformat(s["next_due"]) - self.today).days <= 7]
        month_start = self.today.replace(day=1)
        if month_start.month == 12:
            next_month = date(month_start.year + 1, 1, 1)
        else:
            next_month = date(month_start.year, month_start.month + 1, 1)
        paid = self.db.payments_between(month_start.isoformat(), next_month.isoformat())
        totals = sum_by_currency(paid)
        spent = " · ".join(money(v, k) for k, v in totals.items()) or "0"
        return (
            "💎 <b>VPS BILLING</b>\n\n"
            f"Серверов: <b>{len(servers)}</b>\n"
            f"К оплате ≤ 7 дней: <b>{len(soon)}</b>\n"
            f"Просрочено: <b>{len(overdue)}</b>\n"
            f"Оплачено в этом месяце: <b>{h(spent)}</b>"
        )

    async def _show_main_cb(self, q: CallbackQuery):
        await q.answer()
        await q.message.edit_text(self._main_text(), reply_markup=main_menu())

    def _register(self):
        r = self.router
        r.message.register(self.start, CommandStart())
        r.message.register(self.start, Command("menu"))
        r.callback_query.register(self._show_main_cb, F.data == "main")
        r.callback_query.register(self.servers, F.data == "servers")
        r.callback_query.register(self.server, F.data.startswith("server:"))
        r.callback_query.register(self.upcoming, F.data == "upcoming")
        r.callback_query.register(self.payments, F.data == "payments")
        r.callback_query.register(self.analytics, F.data == "analytics")
        r.callback_query.register(self.settings_page, F.data == "settings")
        r.callback_query.register(self.backup, F.data == "backup")
        r.callback_query.register(self.test_telegram, F.data == "testtg")
        r.callback_query.register(self.paid, F.data.startswith("paid:"))
        r.callback_query.register(self.snooze, F.data.startswith("snooze:"))
        r.callback_query.register(self.delete_ask, F.data.startswith("deleteask:"))
        r.callback_query.register(self.delete_yes, F.data.startswith("deleteyes:"))
        r.callback_query.register(self.add_start, F.data == "add:start")
        r.message.register(self.add_name, AddServer.name)
        r.message.register(self.add_provider, AddServer.provider)
        r.message.register(self.add_amount, AddServer.amount)
        r.callback_query.register(self.add_currency, AddServer.currency, F.data.startswith("cur:"))
        r.message.register(self.add_due, AddServer.due)
        r.callback_query.register(self.add_cycle, AddServer.cycle, F.data.startswith("cycle:"))
        r.callback_query.register(self.change_date_start, F.data.startswith("date:"))
        r.message.register(self.change_date_save, ChangeDate.due)

    async def start(self, m: Message, state: FSMContext):
        await state.clear()
        await m.answer(self._main_text(), reply_markup=main_menu())

    async def servers(self, q: CallbackQuery):
        await q.answer()
        items = self.db.list_servers()
        rows = [[InlineKeyboardButton(text=f"🖥 {s['name']} · {date.fromisoformat(s['next_due']).strftime('%d.%m')}", callback_data=f"server:{s['id']}")] for s in items[:40]]
        rows += [[InlineKeyboardButton(text="➕ Добавить VPS", callback_data="add:start")], [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main")]]
        text = "🖥 <b>Серверы</b>\n\n" + (f"Активных серверов: <b>{len(items)}</b>" if items else "Пока серверов нет.")
        await q.message.edit_text(text, reply_markup=kb(rows))

    async def server(self, q: CallbackQuery):
        await q.answer()
        sid = int(q.data.split(":",1)[1]); s = self.db.get_server(sid)
        if not s:
            return await q.message.edit_text("Сервер не найден.", reply_markup=back_main())
        await q.message.edit_text(server_card(s, self.settings.emojis), reply_markup=server_buttons(sid))

    async def upcoming(self, q: CallbackQuery):
        await q.answer()
        items = self.db.list_servers()
        items = [s for s in items if (date.fromisoformat(s["next_due"]) - self.today).days <= 30]
        lines = ["📅 <b>Ближайшие оплаты</b>", ""]
        for s in items[:30]:
            d = (date.fromisoformat(s["next_due"]) - self.today).days
            tag = f"через {d} дн." if d >= 0 else f"просрочено {abs(d)} дн."
            lines.append(f"• <b>{h(s['name'])}</b> — {money(s['amount_minor'], s['currency'])} · {date.fromisoformat(s['next_due']).strftime('%d.%m')} · {tag}")
        if len(lines)==2: lines.append("На ближайшие 30 дней оплат нет.")
        await q.message.edit_text("\n".join(lines), reply_markup=back_main())

    async def payments(self, q: CallbackQuery):
        await q.answer()
        rows = self.db.recent_payments(25)
        lines = ["💳 <b>История оплат</b>", ""]
        for p in rows:
            pd = datetime.fromisoformat(p["paid_at"]).strftime("%d.%m.%Y")
            lines.append(f"• {pd} · <b>{h(p['name'])}</b> · {money(p['amount_minor'], p['currency'])}")
        if len(lines)==2: lines.append("Оплат пока нет.")
        await q.message.edit_text("\n".join(lines), reply_markup=back_main())

    async def analytics(self, q: CallbackQuery):
        await q.answer()
        today = self.today
        month_start = today.replace(day=1)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        paid = self.db.payments_between(month_start.isoformat(), next_month.isoformat())
        upcoming = self.db.due_between(today.isoformat(), (today + timedelta(days=30)).isoformat())
        pt = sum_by_currency(paid); ut = sum_by_currency(upcoming)
        lines = ["📊 <b>Аналитика</b>", "", "<b>Оплачено в этом месяце:</b>"]
        lines += [f"• {money(v,k)}" for k,v in pt.items()] or ["• 0"]
        lines += ["", "<b>План на 30 дней:</b>"]
        lines += [f"• {money(v,k)}" for k,v in ut.items()] or ["• 0"]
        prov = {}
        for s in self.db.list_servers(): prov[s["provider"] or "Без провайдера"] = prov.get(s["provider"] or "Без провайдера",0)+1
        lines += ["", "<b>Провайдеры:</b>"] + [f"• {h(k)} — {v}" for k,v in sorted(prov.items(), key=lambda x:(-x[1],x[0]))[:15]]
        await q.message.edit_text("\n".join(lines), reply_markup=back_main())

    async def settings_page(self, q: CallbackQuery):
        await q.answer()
        dbi = self.db.integrity()
        text = ("⚙️ <b>Настройки</b>\n\n"
                f"Telegram: <b>SOCKS5</b> · <code>{h(mask_proxy(self.settings.telegram_proxy))}</code>\n" if self.settings.telegram_proxy else "⚙️ <b>Настройки</b>\n\nTelegram: <b>напрямую</b>\n")
        text += f"База: <b>{h(dbi['integrity'])}</b> · schema {dbi['schema_version']}\nTimezone: <b>{h(self.settings.timezone)}</b>"
        await q.message.edit_text(text, reply_markup=kb([
            [InlineKeyboardButton(text="🧪 Проверить Telegram", callback_data="testtg"), InlineKeyboardButton(text="💾 Backup", callback_data="backup")],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main")],
        ]))

    async def backup(self, q: CallbackQuery):
        await q.answer("Создаю backup…")
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = self.settings.backups_dir / f"billing-{ts}.db"
        self.db.backup_to(out)
        await q.message.edit_text(f"💾 <b>Backup создан</b>\n\n<code>{h(out.name)}</code>", reply_markup=back_main())

    async def test_telegram(self, q: CallbackQuery):
        try:
            me = await q.bot.get_me(); await q.answer("Telegram OK", show_alert=True)
            await q.message.edit_text(f"🟢 <b>Telegram доступен</b>\n\nBot: @{h(me.username)}\nProxy: <code>{h(mask_proxy(self.settings.telegram_proxy))}</code>", reply_markup=back_main())
        except Exception as e:
            await q.answer("Ошибка Telegram", show_alert=True)
            await q.message.edit_text(f"🔴 <b>Telegram недоступен</b>\n\n<code>{h(str(e)[:500])}</code>", reply_markup=back_main())

    async def paid(self, q: CallbackQuery):
        sid = int(q.data.split(":",1)[1]); s = self.db.get_server(sid)
        if not s: return await q.answer("Сервер не найден", show_alert=True)
        nd = next_due(s["next_due"], s["cycle"], s["cycle_days"])
        self.db.add_payment(sid, s["amount_minor"], s["currency"], s["next_due"], nd)
        await q.answer("Оплата сохранена ✅")
        s = self.db.get_server(sid)
        await q.message.edit_text("✅ <b>Оплачено</b>\n\n" + server_card(s, self.settings.emojis), reply_markup=server_buttons(sid))

    async def snooze(self, q: CallbackQuery):
        sid=int(q.data.split(":",1)[1]); until=datetime.now(ZoneInfo(self.settings.timezone))+timedelta(days=1)
        until=until.replace(hour=9,minute=0,second=0,microsecond=0)
        self.db.snooze_until(sid, until.isoformat())
        await q.answer("Напомню завтра")

    async def delete_ask(self, q: CallbackQuery):
        sid=int(q.data.split(":",1)[1]); s=self.db.get_server(sid); await q.answer()
        if not s: return
        await q.message.edit_text(f"🗑 Удалить <b>{h(s['name'])}</b> вместе с историей его оплат?", reply_markup=kb([[InlineKeyboardButton(text="🔴 Да, удалить", callback_data=f"deleteyes:{sid}"), InlineKeyboardButton(text="Отмена", callback_data=f"server:{sid}")]]))

    async def delete_yes(self, q: CallbackQuery):
        sid=int(q.data.split(":",1)[1]); self.db.delete_server(sid); await q.answer("Удалено")
        items = self.db.list_servers()
        rows = [[InlineKeyboardButton(text=f"🖥 {x['name']} · {date.fromisoformat(x['next_due']).strftime('%d.%m')}", callback_data=f"server:{x['id']}")] for x in items[:40]]
        rows += [[InlineKeyboardButton(text="➕ Добавить VPS", callback_data="add:start")], [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main")]]
        await q.message.edit_text("🖥 <b>Серверы</b>", reply_markup=kb(rows))

    async def add_start(self, q: CallbackQuery, state: FSMContext):
        await q.answer(); await state.clear(); await state.set_state(AddServer.name)
        await q.message.edit_text("➕ <b>Новый VPS</b>\n\nВведите название сервера:\nНапример: <code>rw-node-fi4</code>")

    async def add_name(self, m: Message, state: FSMContext):
        if not m.text: return
        await state.update_data(name=m.text.strip()); await state.set_state(AddServer.provider); await m.answer("Провайдер?\nНапример: <code>Hetzner</code>")

    async def add_provider(self, m: Message, state: FSMContext):
        if not m.text: return
        await state.update_data(provider=m.text.strip()); await state.set_state(AddServer.amount); await m.answer("Стоимость за период?\nНапример: <code>15.90</code>")

    async def add_amount(self, m: Message, state: FSMContext):
        try: amount=parse_amount_minor(m.text or "")
        except ValueError as e: return await m.answer(f"⚠️ {h(e)}. Введите сумму ещё раз:")
        await state.update_data(amount_minor=amount); await state.set_state(AddServer.currency)
        await m.answer("Валюта:", reply_markup=kb([[InlineKeyboardButton(text=x, callback_data=f"cur:{x}") for x in ("RUB","EUR","USD")],[InlineKeyboardButton(text=x, callback_data=f"cur:{x}") for x in ("CNY","TRY")]]))

    async def add_currency(self, q: CallbackQuery, state: FSMContext):
        await q.answer(); await state.update_data(currency=q.data.split(":",1)[1]); await state.set_state(AddServer.due)
        await q.message.edit_text("Дата ближайшей оплаты?\nНапример: <code>25.09.2026</code>")

    async def add_due(self, m: Message, state: FSMContext):
        try: d=parse_date(m.text or "")
        except ValueError as e: return await m.answer(f"⚠️ {h(e)}")
        await state.update_data(next_due=d.isoformat()); await state.set_state(AddServer.cycle)
        await m.answer("Период оплаты:", reply_markup=kb([
            [InlineKeyboardButton(text="Каждый месяц", callback_data="cycle:monthly"), InlineKeyboardButton(text="3 месяца", callback_data="cycle:quarterly")],
            [InlineKeyboardButton(text="6 месяцев", callback_data="cycle:semiannual"), InlineKeyboardButton(text="Год", callback_data="cycle:yearly")],
        ]))

    async def add_cycle(self, q: CallbackQuery, state: FSMContext):
        await q.answer(); data=await state.get_data(); cycle=q.data.split(":",1)[1]
        sid=self.db.add_server(name=data["name"],provider=data["provider"],amount_minor=data["amount_minor"],currency=data["currency"],next_due=data["next_due"],cycle=cycle)
        await state.clear(); s=self.db.get_server(sid)
        await q.message.edit_text("✅ <b>VPS добавлен</b>\n\n"+server_card(s,self.settings.emojis),reply_markup=server_buttons(sid))

    async def change_date_start(self, q: CallbackQuery, state: FSMContext):
        sid=int(q.data.split(":",1)[1]); await q.answer(); await state.set_state(ChangeDate.due); await state.update_data(server_id=sid)
        await q.message.edit_text("📅 Введите новую дату оплаты:\nНапример: <code>25.10.2026</code>")

    async def change_date_save(self, m: Message, state: FSMContext):
        try: d=parse_date(m.text or "")
        except ValueError as e: return await m.answer(f"⚠️ {h(e)}")
        data=await state.get_data(); sid=int(data["server_id"]); self.db.update_due(sid,d.isoformat()); await state.clear(); s=self.db.get_server(sid)
        await m.answer("✅ Дата изменена\n\n"+server_card(s,self.settings.emojis),reply_markup=server_buttons(sid))
