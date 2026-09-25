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

TMP=$(mktemp -d /tmp/vps-bill-restore.XXXXXX)
RESTORE_TMP=""
trap 'rm -rf "$TMP"; [[ -z "${RESTORE_TMP:-}" ]] || rm -f -- "$RESTORE_TMP"' EXIT
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
DB="$BASE/data/billing.db"
SAFETY="$BASE/backups/vps-bill-pre-restore-${TS}.db"
SAFETY_DIR="/opt/vps-bill-safety"
mkdir -p "$BASE/data" "$BASE/backups"
chown 10001:10001 "$BASE/data" "$BASE/backups"
install -d -o root -g root -m 0700 "$SAFETY_DIR"

if [[ -s "$DB" ]]; then
  docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli backup --output "/app/backups/$(basename "$SAFETY")" >/dev/null
  [[ -s "$SAFETY" ]] || { echo "Не удалось создать страховочную копию текущей базы" >&2; exit 1; }
  cp -- "$SAFETY" "$SAFETY_DIR/$(basename "$SAFETY")"
  chmod 0600 "$SAFETY_DIR/$(basename "$SAFETY")"
else
  echo "! Текущая база отсутствует: восстановление продолжится без pre-restore копии."
fi

RESTORE_TMP="$BASE/data/.billing.restore-${TS}.$$.db"
cp -- "$DBSRC" "$RESTORE_TMP"
chown 10001:10001 "$RESTORE_TMP"
chmod 0640 "$RESTORE_TMP"
python3 - "$RESTORE_TMP" <<'PYRESTORE'
import sqlite3,sys
p=sys.argv[1]
con=sqlite3.connect(f"file:{p}?mode=ro", uri=True)
r=con.execute("PRAGMA quick_check").fetchone(); con.close()
if not r or r[0] != "ok": raise SystemExit(f"Restore quick_check: {r[0] if r else 'no result'}")
PYRESTORE

docker compose -f "$COMPOSE" --env-file "$ENV" down
mv -f -- "$RESTORE_TMP" "$DB"
RESTORE_TMP=""
rm -f -- "$DB-wal" "$DB-shm"
chown 10001:10001 "$DB"; chmod 0640 "$DB"
touch "$BASE/data/.initialized"; chown 10001:10001 "$BASE/data/.initialized"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli migrate >/dev/null
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli db-check >/dev/null
docker compose -f "$COMPOSE" --env-file "$ENV" up -d
echo "Восстановлено: $SRC"
[[ -s "$SAFETY" ]] && echo "Страховочная копия предыдущей базы: $SAFETY"
