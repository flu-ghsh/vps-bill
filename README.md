# VPS Bill

Telegram-бот для учёта VPS и серверов, расходов, дат оплаты, заметок и мониторинга.

## Возможности

- учёт серверов и VPS;
- провайдеры, страны и IP;
- стоимость и даты оплаты;
- история платежей;
- заметки;
- мониторинг;
- аналитика;
- backup / restore;
- обновление через GitHub Releases.

## Установка

Одна команда:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/flu-ghsh/vps-bill/main/install.sh)
```

Установщик запросит:

- Bot Token;
- Telegram numeric ID;
- SOCKS5 при необходимости;
- timezone.

Если SOCKS5 оставить пустым, Telegram будет работать напрямую.

После установки проект находится в:

```text
/opt/vps-bill
```

## Основные команды

Статус:

```bash
docker compose -f /opt/vps-bill/compose.yaml \
  --env-file /opt/vps-bill/.env ps
```

Логи:

```bash
docker logs -f vps-bill
```

Обновление:

```bash
vps-bill-update
```

Backup:

```bash
vps-bill-backup
```

Restore:

```bash
vps-bill-restore
```

## Обновления

`vps-bill-update` проверяет последний опубликованный GitHub Release.

Если доступна новая версия, updater:

- скачает релиз;
- создаст backup базы;
- соберёт новый Docker image;
- выполнит миграцию;
- переключит активную версию;
- проверит запуск;
- при ошибке выполнит rollback.

Текущая версия:

```bash
cat /opt/vps-bill/current/VERSION
```

## Данные

Рабочая база:

```text
/opt/vps-bill/data/billing.db
```

Резервные копии:

```text
/opt/vps-bill/backups/
```

Конфигурация:

```text
/opt/vps-bill/.env
```

`.env`, база и backup-файлы не публикуются в Git.

## Структура

```text
/opt/vps-bill/
├── .env
├── compose.yaml
├── current -> releases/<version>
├── data/
├── backups/
└── releases/
```

## GitHub Releases

Стабильные версии публикуются здесь:

https://github.com/flu-ghsh/vps-bill/releases

Репозиторий:

https://github.com/flu-ghsh/vps-bill

## Лицензия

MIT
