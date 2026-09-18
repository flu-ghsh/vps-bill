from __future__ import annotations

from datetime import date, datetime
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .billing import cycle_label, days_until, money
from .config import EmojiConfig


def h(value) -> str:
    return escape(str(value or ""))


def premium(emoji_id: str | None, fallback: str) -> str:
    if emoji_id:
        return f'<tg-emoji emoji-id="{h(emoji_id)}">{fallback}</tg-emoji>'
    return fallback


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🖥 Серверы", callback_data="servers"), InlineKeyboardButton(text="💳 Платежи", callback_data="payments")],
        [InlineKeyboardButton(text="📊 Аналитика", callback_data="analytics"), InlineKeyboardButton(text="➕ Добавить VPS", callback_data="add:start")],
        [InlineKeyboardButton(text="📅 Ближайшие", callback_data="upcoming"), InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings")],
    ])


def back_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main")]])


def server_buttons(server_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплатил", callback_data=f"paid:{server_id}"), InlineKeyboardButton(text="⏰ Завтра", callback_data=f"snooze:{server_id}")],
        [InlineKeyboardButton(text="📅 Изменить дату", callback_data=f"date:{server_id}"), InlineKeyboardButton(text="🗑 Удалить", callback_data=f"deleteask:{server_id}")],
        [InlineKeyboardButton(text="⬅️ К серверам", callback_data="servers")],
    ])


def notification_buttons(server_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Оплатил", callback_data=f"paid:{server_id}"), InlineKeyboardButton(text="⏰ Напомнить завтра", callback_data=f"snooze:{server_id}")],
        [InlineKeyboardButton(text="🖥 Открыть сервер", callback_data=f"server:{server_id}")],
    ])


def server_card(server: dict, emojis: EmojiConfig) -> str:
    d = days_until(server["next_due"])
    if d < 0:
        when = f"🔴 просрочено на {abs(d)} дн."
    elif d == 0:
        when = "🟠 сегодня"
    elif d == 1:
        when = "🟡 завтра"
    else:
        when = f"через {d} дн."
    return (
        f"{premium(emojis.server, '🖥')} <b>{h(server['name'])}</b>\n\n"
        f"Провайдер: <b>{h(server['provider'] or '—')}</b>\n"
        f"Стоимость: <b>{money(server['amount_minor'], server['currency'])}</b>\n"
        f"Оплата: <b>{date.fromisoformat(server['next_due']).strftime('%d.%m.%Y')}</b> · {when}\n"
        f"Период: {h(cycle_label(server['cycle'], server['cycle_days']))}"
        + (f"\n\n📝 {h(server['notes'])}" if server.get("notes") else "")
    )
