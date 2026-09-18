from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _admin_ids() -> frozenset[int]:
    raw = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "")).strip()
    if not raw:
        raise RuntimeError("ADMIN_IDS is required")
    result: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            result.add(int(part))
    if not result:
        raise RuntimeError("ADMIN_IDS contains no valid IDs")
    return frozenset(result)


def normalize_proxy(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith("socks5h://"):
        value = "socks5://" + value[len("socks5h://"):]
    if "://" not in value:
        value = "socks5://" + value
    if not value.startswith(("socks5://", "socks4://", "http://", "https://")):
        raise RuntimeError("TELEGRAM_PROXY must be host:port or a supported proxy URL")
    return value


def mask_proxy(value: str | None) -> str:
    if not value:
        return "напрямую"
    try:
        p = urlsplit(value)
        host = p.hostname or "?"
        port = f":{p.port}" if p.port else ""
        return urlunsplit((p.scheme, f"{host}{port}", "", "", ""))
    except Exception:
        return "настроен"


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _reminder_days() -> tuple[int, ...]:
    raw = os.getenv("REMINDER_DAYS", "7,3,1,0")
    out: list[int] = []
    for p in raw.split(","):
        p = p.strip()
        if p:
            out.append(int(p))
    return tuple(sorted(set(out), reverse=True))


@dataclass(frozen=True)
class EmojiConfig:
    money: str | None = field(default_factory=lambda: os.getenv("EMOJI_MONEY_ID") or None)
    server: str | None = field(default_factory=lambda: os.getenv("EMOJI_SERVER_ID") or None)
    chart: str | None = field(default_factory=lambda: os.getenv("EMOJI_CHART_ID") or None)
    calendar: str | None = field(default_factory=lambda: os.getenv("EMOJI_CALENDAR_ID") or None)
    settings: str | None = field(default_factory=lambda: os.getenv("EMOJI_SETTINGS_ID") or None)
    ok: str | None = field(default_factory=lambda: os.getenv("EMOJI_OK_ID") or None)
    warning: str | None = field(default_factory=lambda: os.getenv("EMOJI_WARNING_ID") or None)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    telegram_proxy: str | None
    timezone: str
    check_interval: int
    reminder_days: tuple[int, ...]
    monthly_report_enabled: bool
    report_hour: int
    db_path: Path
    backups_dir: Path
    update_manifest_url: str | None
    emojis: EmojiConfig

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bot_token=_required("BOT_TOKEN"),
            admin_ids=_admin_ids(),
            telegram_proxy=normalize_proxy(os.getenv("TELEGRAM_PROXY")),
            timezone=os.getenv("TZ", "Europe/Moscow"),
            check_interval=max(30, int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))),
            reminder_days=_reminder_days(),
            monthly_report_enabled=_bool_env("MONTHLY_REPORT_ENABLED", True),
            report_hour=max(0, min(23, int(os.getenv("REPORT_HOUR", "10")))),
            db_path=Path(os.getenv("DB_PATH", "/app/data/billing.db")),
            backups_dir=Path(os.getenv("BACKUPS_DIR", "/app/backups")),
            update_manifest_url=os.getenv("UPDATE_MANIFEST_URL") or None,
            emojis=EmojiConfig(),
        )
