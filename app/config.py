from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _env_value(name: str, default: str = "") -> str:
    """Read a scalar from environment and tolerate dotenv-style outer quotes.

    Docker Compose strips quotes from env_file values, while `docker run --env-file`
    may pass them literally. Updates use both code paths, so config parsing must
    accept either representation.
    """
    value = os.getenv(name, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
        value = value[1:-1].strip()
    return value


def _required(name: str) -> str:
    value = _env_value(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


def _admin_ids() -> frozenset[int]:
    raw = _env_value("ADMIN_IDS", _env_value("ADMIN_ID"))
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


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    telegram_proxy: str | None
    timezone: str
    check_interval: int
    db_path: Path
    backups_dir: Path
    update_manifest_url: str | None
    update_requests_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bot_token=_required("BOT_TOKEN"),
            admin_ids=_admin_ids(),
            telegram_proxy=normalize_proxy(_env_value("TELEGRAM_PROXY") or None),
            timezone=_env_value("TZ", "Europe/Moscow"),
            check_interval=max(30, int(_env_value("CHECK_INTERVAL_SECONDS", "60"))),
            db_path=Path(_env_value("DB_PATH", "/app/data/billing.db")),
            backups_dir=Path(_env_value("BACKUPS_DIR", "/app/backups")),
            update_manifest_url=_env_value("UPDATE_MANIFEST_URL") or None,
            update_requests_dir=Path("/app/update-requests"),
        )
