from __future__ import annotations

import calendar as pycalendar
from datetime import date
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .billing import cycle_label, days_until, money


EMOJI_SLOTS: dict[str, tuple[str, str]] = {
    "brand": ("💎", "Логотип"),
    "server": ("🖥", "Серверы"),
    "payments": ("💳", "Платежи"),
    "analytics": ("📊", "Аналитика"),
    "add": ("➕", "Добавить"),
    "calendar": ("📅", "Календарь"),
    "settings": ("⚙️", "Настройки"),
    "update": ("⬆️", "Обновление"),
    "paid": ("✅", "Оплачено"),
    "snooze": ("⏰", "Напомнить"),
    "delete": ("🗑", "Удалить"),
    "cancel": ("❌", "Отмена"),
    "back": ("⬅️", "Назад"),
    "provider": ("🏢", "Хостер"),
    "cabinet": ("↗️", "Переход в ЛК"),
    "backup": ("💾", "Backup"),
    "warning": ("⚠️", "Предупреждение"),
    "money": ("💸", "Оплата"),
    "reminders": ("🔔", "Напоминания"),
    "reports": ("📈", "Отчёт"),
    "emoji": ("🎨", "Эмодзи"),
    "cycle": ("🔁", "Периоды"),
    "currency_rub": ("₽", "RUB"),
    "currency_eur": ("€", "EUR"),
    "currency_usd": ("$", "USD"),
    "reset": ("♻️", "Сброс"),
    "notes": ("📝", "Заметка"),
    "status_overdue": ("🔴", "Просрочено"),
    "status_today": ("🟠", "Сегодня"),
    "status_tomorrow": ("🟡", "Завтра"),
    "status_active": ("🟢", "Активен"),
    "tags": ("🏷", "Теги"),
    "edit": ("✏️", "Данные"),
    "ip": ("🌐", "IP"),
    "country": ("🌍", "Страна"),
    "trash": ("🗑", "Корзина"),
    "restore": ("↩️", "Восстановить"),
    "purge": ("🔥", "Удалить навсегда"),
    "monitor": ("📡", "Доступность"),
    "status_down": ("🔴", "Недоступен"),
    "status_up": ("🟢", "Восстановлен"),
}

MONTHS_RU = (
    "",
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
WEEKDAYS_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def h(value) -> str:
    return escape(str(value or ""))


def premium(emoji_id: str | None, fallback: str) -> str:
    if emoji_id:
        return f'<tg-emoji emoji-id="{h(emoji_id)}">{fallback}</tg-emoji>'
    return fallback


def e(emojis: dict[str, str], slot: str) -> str:
    fallback = EMOJI_SLOTS[slot][0]
    return premium(emojis.get(slot), fallback)


def button(
    emojis: dict[str, str],
    slot: str | None,
    label: str,
    callback_data: str,
    *,
    style: str | None = None,
) -> InlineKeyboardButton:
    emoji_id = emojis.get(slot, "") if slot else ""
    if slot and not emoji_id:
        label = f"{EMOJI_SLOTS[slot][0]} {label}"
    return InlineKeyboardButton(
        text=label,
        callback_data=callback_data,
        style=style,
        icon_custom_emoji_id=emoji_id or None,
    )




def pagination_row(emojis: dict[str, str], page: int, total_pages: int, prefix: str) -> list[InlineKeyboardButton]:
    """Compact pagination: arrows + current page. Page is zero-based."""
    if total_pages <= 1:
        return []
    page = max(0, min(page, total_pages - 1))
    prev_cb = f"{prefix}:{page - 1}" if page > 0 else "noop"
    next_cb = f"{prefix}:{page + 1}" if page < total_pages - 1 else "noop"
    return [
        InlineKeyboardButton(text="‹", callback_data=prev_cb),
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"),
        InlineKeyboardButton(text="›", callback_data=next_cb),
    ]

def main_menu(emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            button(emojis, "server", "Серверы", "servers"),
            button(emojis, "payments", "Платежи", "payments"),
        ],
        [
            button(emojis, "analytics", "Аналитика", "analytics"),
            button(emojis, "add", "Добавить VPS", "add:start", style="success"),
        ],
        [
            button(emojis, "calendar", "Ближайшие", "upcoming"),
            button(emojis, "settings", "Настройки", "settings"),
        ],
    ])


def back_main(emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        button(emojis, "back", "Главное меню", "main")
    ]])


def cancel_keyboard(emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        button(emojis, "cancel", "Отмена", "flow:cancel", style="danger")
    ]])


def server_buttons(server_id: int, emojis: dict[str, str], *, balance_mode: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if balance_mode:
        rows.append([button(emojis, "payments", "Пополнил баланс", f"balance:topup:{server_id}", style="success")])
    else:
        rows.append([
            button(emojis, "paid", "Оплатил", f"paid:{server_id}", style="success"),
            button(emojis, "snooze", "Напомнить завтра", f"snooze:{server_id}"),
        ])
        rows.append([
            button(emojis, "edit", "Данные", f"details:{server_id}"),
            button(emojis, "calendar", "Дата оплаты", f"date:{server_id}"),
        ])
    if balance_mode:
        rows.append([button(emojis, "edit", "Данные", f"details:{server_id}")])
    rows.append([button(emojis, "server", "В архив", f"archiveask:{server_id}")])
    rows.append([button(emojis, "trash", "В корзину", f"trashask:{server_id}", style="danger")])
    rows.append([button(emojis, "back", "К серверам", "servers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def server_details_keyboard(server_id: int, emojis: dict[str, str], *, has_ip: bool = False, has_country: bool = False, has_tags: bool = False, has_notes: bool = False, monitor_enabled: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            button(emojis, "ip", "IP", f"editfield:{server_id}:ip", style="success" if has_ip else None),
            button(emojis, "country", "Страна", f"country:choose:{server_id}", style="success" if has_country else None),
        ],
        [button(emojis, "tags", "Теги", f"tag:choose:{server_id}", style="success" if has_tags else None)],
        [button(emojis, "notes", "Заметка", f"editfield:{server_id}:notes", style="success" if has_notes else None)],
    ]
    if has_ip:
        rows.append([button(emojis, "monitor", f"Мониторинг: {'ВКЛ' if monitor_enabled else 'ВЫКЛ'}", f"monitor:server:{server_id}", style="success" if monitor_enabled else None)])
    rows.append([button(emojis, "back", "К карточке", f"srvopen:{server_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def country_picker_keyboard(server_id: int, countries: list[str], emojis: dict[str, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    limited = countries[:24]
    for i in range(0, len(limited), 2):
        row = []
        for idx in range(i, min(i + 2, len(limited))):
            row.append(InlineKeyboardButton(text=limited[idx], callback_data=f"country:set:{server_id}:{idx}", style="primary"))
        rows.append(row)
    rows.append([button(emojis, "add", "Новая страна", f"editfield:{server_id}:country", style="success")])
    rows.append([button(emojis, "back", "К карточке", f"details:{server_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tag_picker_keyboard(server_id: int, all_tags: list[str], active_tags: list[str], emojis: dict[str, str]) -> InlineKeyboardMarkup:
    active = {x.casefold() for x in active_tags}
    rows: list[list[InlineKeyboardButton]] = []
    limited = all_tags[:30]
    for i in range(0, len(limited), 3):
        row: list[InlineKeyboardButton] = []
        for idx in range(i, min(i + 3, len(limited))):
            tag = limited[idx]
            row.append(InlineKeyboardButton(text=("✓ " if tag.casefold() in active else "") + tag, callback_data=f"tag:toggle:{server_id}:{idx}", style="primary" if tag.casefold() in active else None))
        rows.append(row)
    rows.append([button(emojis, "add", "Новый тег", f"tag:new:{server_id}", style="success")])
    rows.append([button(emojis, "back", "К карточке", f"details:{server_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def daily_mode_keyboard(emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(emojis, "calendar", "Каждый день вручную", "daily:manual")],
        [button(emojis, "payments", "Оплата с баланса", "daily:balance", style="success")],
        [button(emojis, "cancel", "Отмена", "flow:cancel", style="danger")],
    ])


def balance_alert_keyboard(emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 день", callback_data="balancealert:1"), InlineKeyboardButton(text="3 дня", callback_data="balancealert:3", style="success"), InlineKeyboardButton(text="7 дней", callback_data="balancealert:7")],
        [button(emojis, "cancel", "Отмена", "flow:cancel", style="danger")],
    ])


def monitoring_settings_keyboard(
    enabled: bool,
    interval: int,
    failures: int,
    recovery: int,
    all_state: str,
    method: str,
    tcp_port: int,
    emojis: dict[str, str],
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"Алерты: {'ВКЛ' if enabled else 'ВЫКЛ'}",
        callback_data="monitor:global",
        style="success" if enabled else None,
    )]]

    state_label = {
        "on": "ВКЛ",
        "partial": "ЧАСТИЧНО",
        "off": "ВЫКЛ",
        "none": "НЕТ VPS С IP",
    }.get(all_state, "ВЫКЛ")
    rows.append([button(
        emojis,
        "monitor",
        f"Мониторинг всех VPS с IP: {state_label}",
        "monitor:enableall",
        style="success" if enabled and all_state == "on" else None,
    )])

    method_labels = (("auto", "Авто"), ("ping", "Ping"), ("tcp", "TCP"))
    rows.append([InlineKeyboardButton(
        text=f"✓ {label}" if enabled and method == key else label,
        callback_data=f"monitor:method:{key}",
        style="success" if enabled and method == key else None,
    ) for key, label in method_labels])

    rows.append([InlineKeyboardButton(
        text=f"TCP порт: {tcp_port}",
        callback_data="monitor:tcpport",
        style="success" if enabled and method in {"auto", "tcp"} else None,
    )])

    rows.append([InlineKeyboardButton(
        text=f"✓ {x//60} мин" if enabled and interval == x else f"{x//60} мин",
        callback_data=f"monitor:interval:{x}",
        style="success" if enabled and interval == x else None,
    ) for x in (60, 180, 300, 600)])
    rows.append([InlineKeyboardButton(
        text=f"✓ {x} ошибок" if enabled and failures == x else f"{x} ошибок",
        callback_data=f"monitor:failures:{x}",
        style="success" if enabled and failures == x else None,
    ) for x in (2, 3, 5)])
    rows.append([InlineKeyboardButton(
        text=f"✓ {x} успеха" if enabled and recovery == x else f"{x} успеха",
        callback_data=f"monitor:recovery:{x}",
        style="success" if enabled and recovery == x else None,
    ) for x in (1, 2, 3)])
    rows.append([button(emojis, "back", "К настройкам", "settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trash_list_keyboard(
    items: list[dict],
    emojis: dict[str, str],
    *,
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    start = page * page_size
    page_items = items[start:start + page_size]
    rows: list[list[InlineKeyboardButton]] = []
    for item in page_items:
        rows.append([button(emojis, "trash", item["name"], f"trashitem:{item['id']}", style="danger")])
    nav = pagination_row(emojis, page, total_pages, "trash:page")
    if nav:
        rows.append(nav)
    if items:
        rows.append([button(emojis, "purge", "Удалить все навсегда", "trash:purgeall:ask", style="danger")])
    rows.append([button(emojis, "back", "К серверам", "servers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def trash_item_keyboard(server_id: int, emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(emojis, "restore", "Восстановить", f"restore:{server_id}", style="success")],
        [button(emojis, "purge", "Удалить навсегда", f"purgeask:{server_id}", style="danger")],
        [button(emojis, "back", "Корзина", "trash", style="primary")],
    ])


def backups_keyboard(emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(emojis, "backup", "Создать и прислать backup", "backup:create", style="success")],
        [button(emojis, "trash", "Очистить старые backup", "backup:cleanup")],
        [button(emojis, "back", "К настройкам", "settings")],
    ])


def archive_list_keyboard(items: list[dict], emojis: dict[str, str], *, page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    total_pages = max(1, (len(items) + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    rows=[]
    for item in items[page*page_size:page*page_size+page_size]:
        rows.append([button(emojis, "server", item["name"], f"archiveitem:{item['id']}")])
    nav=pagination_row(emojis,page,total_pages,"archive:page")
    if nav: rows.append(nav)
    rows.append([button(emojis, "back", "К серверам", "servers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def archive_item_keyboard(server_id: int, emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(emojis, "restore", "Вернуть в активные", f"archiverestore:{server_id}", style="success")],
        [button(emojis, "trash", "В корзину", f"archivetotrash:{server_id}", style="danger")],
        [button(emojis, "back", "Архив", "archive")],
    ])


def notification_buttons(server_id: int, emojis: dict[str, str], *, due_date: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            button(emojis, "paid", "Оплатил", f"paid:{server_id}:{due_date}" if due_date else f"paid:{server_id}", style="success"),
            button(emojis, "snooze", "Напомнить завтра", f"snooze:{server_id}"),
        ],
        [button(emojis, "server", "Открыть сервер", f"srvopen:{server_id}")],
    ])


def provider_keyboard(providers: list[str], emojis: dict[str, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, min(len(providers), 20), 2):
        row = []
        for idx in range(i, min(i + 2, len(providers), 20)):
            row.append(button(emojis, "provider", providers[idx], f"provsel:{idx}", style="primary"))
        rows.append(row)
    rows.append([button(emojis, "add", "Новый хостер", "prov:new", style="success")])
    rows.append([button(emojis, "cancel", "Отмена", "flow:cancel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _currency_button(emojis: dict[str, str], code: str, callback_data: str, *, style: str | None = None, checked: bool = False) -> InlineKeyboardButton:
    code = code.upper()
    slot = {"RUB": "currency_rub", "EUR": "currency_eur", "USD": "currency_usd"}.get(code)
    label = ("✓ " if checked else "") + code
    return button(emojis, slot, label, callback_data, style=style) if slot else InlineKeyboardButton(text=label, callback_data=callback_data, style=style)


def currency_keyboard(emojis: dict[str, str], currencies: tuple[str, ...] | list[str]) -> InlineKeyboardMarkup:
    codes = [str(x).upper() for x in currencies]
    if not codes:
        codes = ["RUB", "EUR", "USD"]
    rows: list[list[InlineKeyboardButton]] = []
    # По умолчанию RUB / EUR / USD помещаются в одну строку.
    for i in range(0, len(codes), 3):
        rows.append([_currency_button(emojis, code, f"cur:{code}", style="primary") for code in codes[i:i + 3]])
    rows.append([button(emojis, "cancel", "Отмена", "flow:cancel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def currencies_settings_keyboard(currencies: list[dict], emojis: dict[str, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    # Три валюты в ряд - компактно и совпадает с мастером создания VPS.
    for i in range(0, len(currencies), 3):
        row: list[InlineKeyboardButton] = []
        for item in currencies[i:i + 3]:
            code = str(item["code"]).upper()
            active = bool(item["active"])
            row.append(_currency_button(
                emojis, code, f"currency:toggle:{code}",
                style="success" if active else None, checked=active,
            ))
        rows.append(row)
    rows.append([button(emojis, "add", "Добавить валюту", "currency:add", style="success")])
    rows.append([button(emojis, "reset", "По умолчанию", "currency:default", style="primary")])
    rows.append([button(emojis, "back", "К настройкам", "settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


CYCLE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("daily", "Ежедневно"),
    ("weekly", "1 неделя"),
    ("monthly", "1 месяц"),
    ("quarterly", "3 месяца"),
    ("semiannual", "6 месяцев"),
    ("yearly", "1 год"),
)


def cycle_keyboard(emojis: dict[str, str], enabled: tuple[str, ...]) -> InlineKeyboardMarkup:
    allowed = {key for key, _ in CYCLE_OPTIONS}
    selected = [item for item in CYCLE_OPTIONS if item[0] in set(enabled) and item[0] in allowed]
    if not selected:
        selected = [item for item in CYCLE_OPTIONS if item[0] in {"weekly", "monthly", "quarterly", "yearly"}]
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(selected), 2):
        row = [
            button(emojis, "cycle", label, f"cycle:{key}", style="primary")
            for key, label in selected[i:i + 2]
        ]
        rows.append(row)
    rows.append([button(emojis, "cancel", "Отмена", "flow:cancel", style="danger")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def billing_cycles_keyboard(enabled: tuple[str, ...], emojis: dict[str, str]) -> InlineKeyboardMarkup:
    enabled_set = set(enabled)
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(CYCLE_OPTIONS), 2):
        row: list[InlineKeyboardButton] = []
        for key, label in CYCLE_OPTIONS[i:i + 2]:
            active = key in enabled_set
            row.append(InlineKeyboardButton(
                text=("✓ " if active else "") + label,
                callback_data=f"billcycle:toggle:{key}",
                style="success" if active else None,
            ))
        rows.append(row)
    rows.append([button(emojis, "reset", "По умолчанию", "billcycle:default", style="primary")])
    rows.append([button(emojis, "back", "К настройкам", "settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def calendar_keyboard(
    emojis: dict[str, str],
    year: int,
    month: int,
    prefix: str,
    *,
    today: date | None = None,
) -> InlineKeyboardMarkup:
    today = today or date.today()
    cal = pycalendar.Calendar(firstweekday=0)
    rows: list[list[InlineKeyboardButton]] = []

    prev_month = month - 1
    prev_year = year
    if prev_month == 0:
        prev_month = 12
        prev_year -= 1
    next_month = month + 1
    next_year = year
    if next_month == 13:
        next_month = 1
        next_year += 1

    rows.append([
        InlineKeyboardButton(text="‹", callback_data=f"cal:{prefix}:nav:{prev_year}-{prev_month:02d}"),
        InlineKeyboardButton(text=f"{MONTHS_RU[month]} {year}", callback_data="noop"),
        InlineKeyboardButton(text="›", callback_data=f"cal:{prefix}:nav:{next_year}-{next_month:02d}"),
    ])
    rows.append([InlineKeyboardButton(text=x, callback_data="noop") for x in WEEKDAYS_RU])

    for week in cal.monthdayscalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
                continue
            selected = date(year, month, day)
            row.append(InlineKeyboardButton(
                text=str(day),
                callback_data=f"cal:{prefix}:day:{selected.isoformat()}",
                style="success" if selected == today else None,
            ))
        rows.append(row)

    rows.append([
        button(emojis, "calendar", "Сегодня", f"cal:{prefix}:day:{today.isoformat()}", style="success"),
        button(emojis, "cancel", "Отмена", "flow:cancel", style="danger"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dictionaries_keyboard(emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            button(emojis, "provider", "Хостеры", "dict:provider"),
            button(emojis, "country", "Страны", "dict:country"),
        ],
        [
            button(emojis, "tags", "Теги", "dict:tag"),
            button(emojis, "emoji", "Эмодзи", "settings:emojis"),
        ],
        [button(emojis, "back", "К настройкам", "settings")],
    ])


def dictionary_items_keyboard(kind: str, items: list[str], emojis: dict[str, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    limited = items[:30]
    for i in range(0, len(limited), 2):
        row=[]
        for idx in range(i, min(i + 2, len(limited))):
            row.append(InlineKeyboardButton(text=limited[idx], callback_data=f"dict:item:{kind}:{idx}"))
        rows.append(row)
    rows.append([button(emojis, "back", "К справочникам", "settings:dictionaries")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dictionary_edit_keyboard(kind: str, idx: int, emojis: dict[str, str], provider_url: str = "") -> InlineKeyboardMarkup:
    rows = [[button(emojis, "edit", "Переименовать", f"dict:rename:{kind}:{idx}")]]
    if kind == "provider":
        rows.append([button(emojis, "provider", "Ссылка на ЛК", f"dict:url:{idx}")])
        if provider_url:
            rows.append([InlineKeyboardButton(text="Открыть ЛК", url=provider_url)])
    rows.append([button(emojis, "back", "К списку", f"dict:{kind}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_keyboard(emojis: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            button(emojis, "reminders", "Напоминания", "settings:reminders"),
            button(emojis, "cycle", "Периоды", "settings:billing_cycles"),
        ],
        [
            button(emojis, "money", "Валюты", "settings:currencies"),
            button(emojis, "reports", "Отчёт", "settings:reports"),
        ],
        [button(emojis, "monitor", "Мониторинг", "settings:monitoring")],
        [
            button(emojis, "provider", "Справочники", "settings:dictionaries"),
            button(emojis, "backup", "Бекап", "settings:backups"),
        ],
        [button(emojis, "update", "Обновление", "settings:update")],
        [button(emojis, "back", "Главное меню", "main")],
    ])


def reminder_keyboard(reminder_days: tuple[int, ...], overdue_daily: bool, reminder_time: str, emojis: dict[str, str]) -> InlineKeyboardMarkup:
    selected = set(reminder_days)
    options = (30, 14, 7, 5, 3, 2, 1, 0)
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(options), 2):
        row = []
        for d in options[i:i + 2]:
            label = "В день оплаты" if d == 0 else f"За {d} дн."
            row.append(InlineKeyboardButton(
                text=("✓ " if d in selected else "") + label,
                callback_data=f"rem:toggle:{d}",
                style="success" if d in selected else None,
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(
        text=f"Просрочка ежедневно: {'ВКЛ' if overdue_daily else 'ВЫКЛ'}",
        callback_data="rem:overdue",
        style="success" if overdue_daily else None,
    )])
    preset_times = ("09:00", "10:00", "12:00", "18:00")
    rows.append([
        InlineKeyboardButton(
            text=("✓ " if reminder_time == value else "") + value,
            callback_data=f"rem:time:{value.replace(':', '')}",
            style="success" if reminder_time == value else None,
        ) for value in preset_times
    ])
    rows.append([button(emojis, "edit", "Другое время", "rem:time:manual")])
    rows.append([button(emojis, "reset", "По умолчанию", "rem:default", style="primary")])
    rows.append([button(emojis, "back", "К настройкам", "settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reports_keyboard(enabled: bool, report_day: int, report_hour: int, report_minute: int, emojis: dict[str, str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [[
        InlineKeyboardButton(
            text=f"Месячный отчёт: {'ВКЛ' if enabled else 'ВЫКЛ'}",
            callback_data="report:toggle",
            style="success" if enabled else None,
        )
    ]]

    days = (1, 5, 10, 15, 20, 25, 28)
    rows.append([
        InlineKeyboardButton(
            text=("✓ " if day == report_day else "") + str(day),
            callback_data=f"report:day:{day}",
            style="success" if day == report_day else None,
        ) for day in days[:4]
    ])
    rows.append([
        InlineKeyboardButton(
            text=("✓ " if day == report_day else "") + str(day),
            callback_data=f"report:day:{day}",
            style="success" if day == report_day else None,
        ) for day in days[4:]
    ])
    rows.append([button(emojis, "edit", "Ввести день вручную", "report:day:manual")])

    current_time = f"{report_hour:02d}:{report_minute:02d}"
    times = ("09:00", "10:00", "12:00", "18:00", "21:00")
    rows.append([
        InlineKeyboardButton(
            text=("✓ " if value == current_time else "") + value,
            callback_data=f"report:time:{value.replace(':', '')}",
            style="success" if value == current_time else None,
        ) for value in times[:3]
    ])
    rows.append([
        InlineKeyboardButton(
            text=("✓ " if value == current_time else "") + value,
            callback_data=f"report:time:{value.replace(':', '')}",
            style="success" if value == current_time else None,
        ) for value in times[3:]
    ])
    rows.append([button(emojis, "edit", "Ввести время вручную", "report:time:manual")])
    rows.append([button(emojis, "reset", "По умолчанию", "report:default", style="primary")])
    rows.append([button(emojis, "back", "К настройкам", "settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def emoji_keyboard(emojis: dict[str, str], page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    slots = list(EMOJI_SLOTS.items())
    total_pages = max(1, (len(slots) + page_size - 1) // page_size)
    page = max(0, min(int(page), total_pages - 1))
    chunk = slots[page * page_size:(page + 1) * page_size]
    for i in range(0, len(chunk), 2):
        row = []
        for slot, (fallback, label) in chunk[i:i + 2]:
            current = emojis.get(slot, "")
            row.append(InlineKeyboardButton(
                text=label if current else f"{fallback} {label}",
                callback_data=f"emoji:edit:{slot}:p:{page}",
                icon_custom_emoji_id=current or None,
            ))
        rows.append(row)
    if total_pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="‹", callback_data=f"emoji:page:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="›", callback_data=f"emoji:page:{page + 1}"))
        rows.append(nav)
    rows.append([button(emojis, "reset", "Сбросить все", f"emoji:resetall:p:{page}", style="danger")])
    rows.append([button(emojis, "back", "К справочникам", "settings:dictionaries")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def emoji_edit_keyboard(slot: str, emojis: dict[str, str], page: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [button(emojis, "reset", "Сбросить этот эмодзи", f"emoji:reset:{slot}:p:{page}", style="danger")],
        [button(emojis, "cancel", "Отмена", "emoji:cancel", style="danger")],
    ])


def server_card(server: dict, emojis: dict[str, str]) -> str:
    d = days_until(server["next_due"])
    if server.get("deleted_at"):
        state = f"{e(emojis, 'trash')} в корзине"
        when = "не участвует в напоминаниях"
    elif server.get("archived_at"):
        state = "📦 в архиве"
        when = "не участвует в напоминаниях"
    elif d < 0:
        state = f"{e(emojis, 'status_overdue')} <b>ПРОСРОЧЕНО</b>"
        when = f"на {abs(d)} дн."
    elif d == 0:
        state = f"{e(emojis, 'status_today')} <b>ОПЛАТА СЕГОДНЯ</b>"
        when = "сегодня"
    elif d == 1:
        state = f"{e(emojis, 'status_tomorrow')} <b>ОПЛАТА ЗАВТРА</b>"
        when = "завтра"
    else:
        state = f"{e(emojis, 'status_active')} активен"
        when = f"через {d} дн."

    if str(server.get("billing_mode") or "scheduled") == "balance":
        from datetime import date as _date
        asof_raw = server.get("balance_updated_at")
        try:
            asof = _date.fromisoformat(str(asof_raw)[:10]) if asof_raw else _date.today()
        except ValueError:
            asof = _date.today()
        elapsed = max(0, (_date.today() - asof).days)
        remaining = max(0, int(server.get("balance_minor") or 0) - elapsed * int(server.get("amount_minor") or 0))
        days_left = remaining // max(1, int(server.get("amount_minor") or 1))
        state = f"{e(emojis, 'status_active')} активен"
        lines = [
            f"{e(emojis, 'server')} <b>{h(server['name'])}</b>",
            f"Статус: {state}",
            "",
            f"{e(emojis, 'provider')} <b>{h(server['provider'] or '-')}</b>",
            f"{e(emojis, 'money')} В сутки: <b>{money(server['amount_minor'], server['currency'])}</b>",
            f"{e(emojis, 'payments')} Баланс: <b>{money(remaining, server['currency'])}</b> · примерно <b>{days_left} дн.</b>",
            f"{e(emojis, 'reminders')} Предупредить: когда останется на <b>{int(server.get('balance_alert_days') or 3)} дн.</b>",
        ]
    else:
        lines = [
            f"{e(emojis, 'server')} <b>{h(server['name'])}</b>",
            f"Статус: {state}",
            "",
            f"{e(emojis, 'provider')} <b>{h(server['provider'] or '-')}</b> · {money(server['amount_minor'], server['currency'])}",
            f"{e(emojis, 'calendar')} <b>{date.fromisoformat(server['next_due']).strftime('%d.%m.%y')}</b> · {when}",
            f"{e(emojis, 'cycle')} {h(cycle_label(server['cycle'], server['cycle_days']))}",
        ]
    if server.get("ip"):
        lines.append(f"{e(emojis, 'ip')} <code>{h(server['ip'])}</code>")
        if server.get("monitor_enabled"):
            lines.append(f"{e(emojis, 'monitor')} Мониторинг доступности: <b>включён</b>")
    if server.get("country"):
        lines.append(f"{e(emojis, 'country')} {h(server['country'])}")
    tags = [x.strip() for x in str(server.get("tags") or "").split(",") if x.strip()]
    if tags:
        lines.append(f"{e(emojis, 'tags')} " + " · ".join(f"<code>{h(x)}</code>" for x in tags))
    if server.get("notes"):
        lines.append(f"{e(emojis, 'notes')} {h(server['notes'])}")
    return "\n".join(lines)


def update_settings_keyboard(emojis: dict[str, str], latest_version: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if latest_version:
        rows.append([InlineKeyboardButton(text=f"Установить {latest_version}", callback_data=f"update:install:{latest_version}", style="success")])
    rows.append([InlineKeyboardButton(text="Проверить сейчас", callback_data="update:check")])
    rows.append([button(emojis, "back", "К настройкам", "settings")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def update_offer_keyboard(version: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Установить {version}", callback_data=f"update:install:{version}", style="success")],
        [InlineKeyboardButton(text="Напомнить завтра", callback_data=f"update:tomorrow:{version}")],
        [InlineKeyboardButton(text="Не напоминать об этой версии", callback_data=f"update:ignore:{version}")],
    ])


def update_confirm_keyboard(version: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить обновление", callback_data=f"update:confirm:{version}", style="success")],
        [InlineKeyboardButton(text="Отмена", callback_data="settings:update", style="danger")],
    ])
