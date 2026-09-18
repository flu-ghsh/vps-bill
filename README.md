# VPS Billing Manager 2.0.0

Автономный Telegram-first менеджер оплат VPS. Никакого Infra Billing и отдельной web-панели.

## Что умеет

- собственная SQLite база серверов и оплат;
- добавление VPS прямо в Telegram;
- суммы, валюты, провайдеры, дата и период оплаты;
- уведомления за 7/3/1/0 дней и ежедневные просроченные напоминания;
- `✅ Оплатил` записывает платёж и автоматически переносит следующую дату;
- `⏰ Напомнить завтра`;
- история оплат, ближайшие оплаты, аналитика по валютам;
- автоматический месячный отчёт;
- SOCKS5 применяется только к Telegram Bot API;
- optional Telegram custom/premium emoji IDs;
- backup/restore SQLite;
- безопасное обновление с тестовой миграцией и rollback.

## Единственная рабочая директория

```text
/opt/vps-bill/
├── .env
├── compose.yaml -> current/compose.yaml
├── data/billing.db
├── backups/
├── releases/
└── current -> releases/2.0.0
```

`.env` всегда находится только в `/opt/vps-bill/.env`.

## Установка

```bash
cd /opt/vps-bill
chmod +x install.sh
./install.sh
```

Установщик спросит только Bot Token, Telegram numeric ID, SOCKS5 и timezone.

SOCKS5 можно вводить коротко:

```text
s5.yabadabadoo.ru:1080
```

Он будет сохранён как `socks5://s5.yabadabadoo.ru:1080`. Для aiohttp-socks DNS SOCKS5 резолвится через proxy.

## Управление

```bash
docker compose -f /opt/vps-bill/compose.yaml --env-file /opt/vps-bill/.env ps
docker logs -f vps-bill
billing-bot-backup
billing-bot-restore
billing-bot-update --file /root/vps-bill-2.0.1.tar.gz
```

## Безопасное обновление

`billing-bot-update`:

1. собирает новый image, не останавливая старый бот;
2. делает online backup SQLite;
3. запускает миграцию новой версии на копии backup;
4. проверяет копию через `PRAGMA integrity_check`;
5. только после этого останавливает старую версию;
6. мигрирует реальную БД и запускает новую;
7. проверяет DB + Telegram через SOCKS5;
8. при ошибке восстанавливает backup и предыдущий release.

`.env` при обновлении не заменяется.

## Custom / Premium emoji

В `/opt/vps-bill/.env` можно заполнить `EMOJI_*_ID`. Если ID пустой, бот использует обычный Unicode emoji.
