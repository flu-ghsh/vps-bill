from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from .config import Settings
from .db import Database


def get_db() -> tuple[Settings, Database]:
    s = Settings.from_env()
    return s, Database(s.db_path)


async def telegram_health(s: Settings) -> dict:
    session = AiohttpSession(proxy=s.telegram_proxy) if s.telegram_proxy else AiohttpSession()
    bot = Bot(s.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML), session=session)
    try:
        me = await bot.get_me()
        return {"status": "ok", "bot_id": me.id, "username": me.username}
    finally:
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("db-check")
    h = sub.add_parser("health"); h.add_argument("--telegram", action="store_true"); h.add_argument("--runtime", action="store_true")
    b = sub.add_parser("backup"); b.add_argument("--output")
    sub.add_parser("auto-update-config")
    args = parser.parse_args()

    s, db = get_db()
    if args.cmd == "migrate":
        db.migrate(); info = db.integrity(); print(json.dumps({"status": "ok" if info["integrity"] == "ok" else info["integrity"]}, ensure_ascii=False)); return
    if args.cmd == "db-check":
        info = db.integrity(); print(json.dumps({"status": "ok" if info["integrity"] == "ok" else info["integrity"]}, ensure_ascii=False))
        raise SystemExit(0 if info["integrity"] == "ok" else 1)
    if args.cmd == "backup":
        out = Path(args.output) if args.output else s.backups_dir / f"vps-bill-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        db.backup_to(out); print(str(out)); return
    if args.cmd == "auto-update-config":
        print(json.dumps({"enabled": db.auto_update_enabled(), "manifest_url": db.auto_update_manifest_url() or s.update_manifest_url or ""}, ensure_ascii=False)); return
    if args.cmd == "health":
        info = db.integrity()
        result = {"db": {"status": "ok" if info["integrity"] == "ok" else info["integrity"]}, "runtime": "skipped", "telegram": "skipped"}
        healthy = info["integrity"] == "ok"
        if args.runtime:
            hb = db.get_runtime("notifier_heartbeat")
            runtime_ok = False
            age = None
            if hb:
                try:
                    updated = datetime.fromisoformat(str(hb["updated_at"]))
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    age = max(0, int((datetime.now().astimezone() - updated.astimezone()).total_seconds()))
                    runtime_ok = age <= max(180, s.check_interval * 3)
                except Exception:
                    runtime_ok = False
            result["runtime"] = {"status": "ok" if runtime_ok else "stale", "age_seconds": age}
            healthy = healthy and runtime_ok
        if args.telegram:
            result["telegram"] = asyncio.run(telegram_health(s))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not healthy:
            raise SystemExit(1)
        return


if __name__ == "__main__":
    main()
