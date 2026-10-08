<img width="1774" height="887" alt="VPS BILL - контроль серверов в Telegram" src="https://github.com/user-attachments/assets/3aa1fb4b-5a3a-4afe-b7af-dc7f8ce69e10" />


# VPS Bill

Telegram-бот для учёта VPS, расходов, дат оплаты и мониторинга доступности.

## Возможности

- учёт VPS, хостеров, стран, IP, тегов и заметок;
- стоимость, даты оплаты и история платежей;
- напоминания и аналитика расходов;
- мониторинг доступности серверов;
- backup / restore;
- обновления через GitHub Releases;
- установка обновлений из Telegram;
- опциональные демо-серверы при первой установке.

## Установка

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/flu-ghsh/vps-bill/main/install.sh)
```

Установщик запросит Bot Token, Telegram ID, SOCKS5 при необходимости, timezone и предложит добавить демо-серверы.

После установки:

```text
/opt/vps-bill
```

## Команды

```bash
docker logs -f vps-bill
vps-bill-update
vps-bill-backup
vps-bill-restore
```

Текущая версия:

```bash
cat /opt/vps-bill/current/VERSION
```

## Данные

```text
База:     /opt/vps-bill/data/billing.db
Backups:  /opt/vps-bill/backups/
Config:   /opt/vps-bill/.env
```

## GitHub

Репозиторий: https://github.com/flu-ghsh/vps-bill

Releases: https://github.com/flu-ghsh/vps-bill/releases

## Лицензия

MIT
