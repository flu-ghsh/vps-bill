#!/usr/bin/env bash
set -Eeuo pipefail
BASE=/opt/vps-bill; ENV="$BASE/.env"; COMPOSE="$BASE/compose.yaml"
[[ $EUID -eq 0 ]] || { echo "Запустите от root" >&2; exit 1; }
[[ -f "$ENV" && -f "$COMPOSE" ]] || { echo "VPS Bill не установлен" >&2; exit 1; }

SRC=""
if [[ "${1:-}" == "--file" ]]; then
  SRC="${2:-}"
  [[ -f "$SRC" ]] || { echo "Файл не найден: $SRC" >&2; exit 1; }
elif [[ -n "${1:-}" ]]; then
  echo "Использование: vps-bill-restore [--file backup.tar.gz|backup.db]" >&2
  exit 2
else
  mapfile -t FILES < <(find "$BASE/backups" -maxdepth 1 -type f \( -name '*.tar.gz' -o -name '*.db' \) -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
  ((${#FILES[@]})) || { echo "Backup-файлы не найдены" >&2; exit 1; }
  echo "Доступные backup:"
  for i in "${!FILES[@]}"; do printf '%2d) %s\n' "$((i+1))" "$(basename "${FILES[$i]}")"; done
  read -r -p "Выберите номер: " N </dev/tty
  [[ "$N" =~ ^[0-9]+$ ]] && ((N>=1 && N<=${#FILES[@]})) || { echo "Неверный номер" >&2; exit 1; }
  SRC="${FILES[$((N-1))]}"
fi

TMP=$(mktemp -d /tmp/vps-bill-restore.XXXXXX); trap 'rm -rf "$TMP"' EXIT
DBSRC="$SRC"
if [[ "$SRC" == *.tar.gz ]]; then
  tar -tzf "$SRC" | grep -qx 'billing.db' || { echo "В архиве нет billing.db" >&2; exit 1; }
  tar -xzf "$SRC" -C "$TMP" billing.db metadata.json 2>/dev/null || tar -xzf "$SRC" -C "$TMP" billing.db
  DBSRC="$TMP/billing.db"
  if [[ -f "$TMP/metadata.json" ]]; then
    echo "Информация о backup:"
    python3 - <<'PY' "$TMP/metadata.json"
import json,sys
m=json.load(open(sys.argv[1], encoding='utf-8'))
print(f"  Версия: {m.get('version','?')}")
print(f"  Создан: {m.get('created_at','?')}")
PY
  fi
fi
[[ -s "$DBSRC" ]] || { echo "Backup пуст" >&2; exit 1; }

# Verify backup using the currently installed image before stopping the bot.
mkdir -p "$TMP/check"; cp "$DBSRC" "$TMP/check/billing.db"; chown -R 10001:10001 "$TMP/check"
docker run --rm --env-file "$ENV" -e DB_PATH=/check/billing.db -v "$TMP/check:/check" "vps-bill:$(grep '^APP_VERSION=' "$ENV" | cut -d= -f2- | tr -d '"')" python -m app.cli db-check >/dev/null

echo "Backup проверен: $(basename "$SRC")"
read -r -p "Восстановить его? Текущая база будет предварительно сохранена. [y/N]: " YES </dev/tty
[[ "$YES" =~ ^[YyДд]$ ]] || exit 0

TS=$(date +%Y%m%d-%H%M%S)
SAFETY="$BASE/backups/vps-bill-pre-restore-${TS}.db"
mkdir -p "$BASE/backups"; chown 10001:10001 "$BASE/backups"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli backup --output "/app/backups/$(basename "$SAFETY")" >/dev/null

docker compose -f "$COMPOSE" --env-file "$ENV" down
rm -f "$BASE/data/billing.db" "$BASE/data/billing.db-wal" "$BASE/data/billing.db-shm"
cp "$DBSRC" "$BASE/data/billing.db"; chown 10001:10001 "$BASE/data/billing.db"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli migrate >/dev/null
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli db-check >/dev/null
docker compose -f "$COMPOSE" --env-file "$ENV" up -d
echo "Восстановлено: $SRC"
echo "Страховочная копия предыдущей базы: $SAFETY"
