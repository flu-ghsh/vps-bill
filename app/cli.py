from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from .config import Settings, mask_proxy
from .db import Database


def get_db() -> tuple[Settings, Database]:
    s = Settings.from_env()
    return s, Database(s.db_path)


async def telegram_health(s: Settings) -> dict:
    session = AiohttpSession(proxy=s.telegram_proxy) if s.telegram_proxy else AiohttpSession()
    bot = Bot(s.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML), session=session)
    try:
        me = await bot.get_me()
        return {"status": "ok", "bot_id": me.id, "username": me.username, "proxy": mask_proxy(s.telegram_proxy)}
    finally:
        await bot.session.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("db-check")
    h = sub.add_parser("health"); h.add_argument("--telegram", action="store_true")
    b = sub.add_parser("backup"); b.add_argument("--output")
    args = parser.parse_args()

    s, db = get_db()
    if args.cmd == "migrate":
        db.migrate(); print(json.dumps(db.integrity(), ensure_ascii=False)); return
    if args.cmd == "db-check":
        info = db.integrity(); print(json.dumps(info, ensure_ascii=False))
        raise SystemExit(0 if info["integrity"] == "ok" else 1)
    if args.cmd == "backup":
        out = Path(args.output) if args.output else s.backups_dir / f"billing-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        db.backup_to(out); print(str(out)); return
    if args.cmd == "health":
        result = {"db": db.integrity(), "telegram": "skipped"}
        if args.telegram:
            result["telegram"] = asyncio.run(telegram_health(s))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["db"]["integrity"] != "ok": raise SystemExit(1)
        return


if __name__ == "__main__":
    main()
