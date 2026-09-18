from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable

from dateutil.relativedelta import relativedelta


def parse_amount_minor(value: str) -> int:
    raw = value.strip().replace(" ", "").replace(",", ".")
    try:
        d = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Некорректная сумма") from exc
    if d < 0:
        raise ValueError("Сумма не может быть отрицательной")
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money(amount_minor: int, currency: str) -> str:
    amount = Decimal(amount_minor) / Decimal(100)
    value = f"{amount:,.2f}".replace(",", " ")
    if value.endswith(".00"):
        value = value[:-3]
    symbols = {"RUB": "₽", "USD": "$", "EUR": "€", "CNY": "¥", "TRY": "₺"}
    symbol = symbols.get(currency.upper())
    return f"{value} {symbol or currency.upper()}"


def parse_date(value: str) -> date:
    raw = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    raise ValueError("Дата должна быть в формате ДД.ММ.ГГГГ или YYYY-MM-DD")


def next_due(current: str, cycle: str, cycle_days: int | None = None) -> str:
    d = date.fromisoformat(current)
    if cycle == "monthly":
        d = d + relativedelta(months=1)
    elif cycle == "quarterly":
        d = d + relativedelta(months=3)
    elif cycle == "semiannual":
        d = d + relativedelta(months=6)
    elif cycle == "yearly":
        d = d + relativedelta(years=1)
    elif cycle == "custom":
        if not cycle_days or cycle_days < 1:
            raise ValueError("Для custom нужен cycle_days > 0")
        d = d + timedelta(days=cycle_days)
    else:
        raise ValueError(f"Неизвестный цикл: {cycle}")
    return d.isoformat()


def days_until(due_iso: str, today: date | None = None) -> int:
    today = today or date.today()
    return (date.fromisoformat(due_iso) - today).days


def cycle_label(cycle: str, cycle_days: int | None = None) -> str:
    labels = {
        "monthly": "ежемесячно",
        "quarterly": "раз в 3 месяца",
        "semiannual": "раз в 6 месяцев",
        "yearly": "ежегодно",
    }
    if cycle == "custom":
        return f"каждые {cycle_days} дн."
    return labels.get(cycle, cycle)


def sum_by_currency(rows: Iterable[dict], amount_key: str = "amount_minor") -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for row in rows:
        out[row["currency"].upper()] += int(row[amount_key])
    return dict(out)
