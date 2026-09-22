#!/usr/bin/env bash
set -Eeuo pipefail
BASE=/opt/vps-bill; ENV="$BASE/.env"; COMPOSE="$BASE/compose.yaml"; LOCK=/var/lock/vps-bill-update.lock
exec 9>"$LOCK"; flock -n 9 || { echo "Обновление уже выполняется" >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Запустите от root" >&2; exit 1; }
[[ -f "$ENV" && -L "$BASE/current" ]] || { echo "VPS Bill не установлен" >&2; exit 1; }

FILE=""; MANIFEST_ARG=""; case "${1:-}" in --file) FILE="${2:-}";; --manifest) MANIFEST_ARG="${2:-}";; "") ;; *) echo "Использование: vps-bill-update [--file release.tar.gz|--manifest URL]" >&2; exit 2;; esac
TMP=$(mktemp -d /tmp/vps-bill-update.XXXXXX); trap 'rm -rf "$TMP"' EXIT
OLD=$(tr -d '[:space:]' < "$BASE/current/VERSION")

if [[ -z "$FILE" ]]; then
  MANIFEST="$MANIFEST_ARG"
  if [[ -z "$MANIFEST" ]]; then MANIFEST=$(grep '^UPDATE_MANIFEST_URL=' "$ENV" | head -1 | cut -d= -f2- | sed 's/^"//;s/"$//' || true); fi
  [[ -n "$MANIFEST" ]] || { echo "UPDATE_MANIFEST_URL пуст. Используйте: vps-bill-update --file release.tar.gz" >&2; exit 1; }
  echo "Получаю manifest: $MANIFEST"
  curl -fsSL "$MANIFEST" -o "$TMP/latest.json"
  URL=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["url"])' "$TMP/latest.json")
  SHA=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("sha256", ""))' "$TMP/latest.json")
  FILE="$TMP/release.tar.gz"; curl -fL "$URL" -o "$FILE"
  if [[ -n "$SHA" ]]; then echo "$SHA  $FILE" | sha256sum -c - >/dev/null || { echo "SHA256 не совпал" >&2; exit 1; }; fi
fi
[[ -f "$FILE" ]] || { echo "Файл не найден: $FILE" >&2; exit 1; }

tar -xzf "$FILE" -C "$TMP"
VF=$(find "$TMP" -maxdepth 3 -type f -name VERSION | head -1)
[[ -n "$VF" ]] || { echo "VERSION не найден в release" >&2; exit 1; }
SRC=$(dirname "$VF"); NEW=$(tr -d '[:space:]' < "$VF")
[[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Некорректная версия: $NEW" >&2; exit 1; }
[[ -f "$SRC/Dockerfile" && -f "$SRC/compose.yaml" && -d "$SRC/app" ]] || { echo "Неполный release" >&2; exit 1; }
if [[ "$NEW" == "$OLD" ]]; then echo "Уже установлена версия $NEW"; exit 0; fi

echo "Обновление $OLD -> $NEW"
TARGET="$BASE/releases/$NEW"; rm -rf "$TARGET"; mkdir -p "$TARGET"; cp -a "$SRC"/. "$TARGET"/
chmod +x "$TARGET/scripts"/*.sh

echo "[1/7] Собираю новый image, старый бот продолжает работать"
docker build -t "vps-bill:$NEW" "$TARGET" >/tmp/vps-bill-update-build.log 2>&1 || { cat /tmp/vps-bill-update-build.log; exit 1; }

echo "[2/7] Создаю online backup"
TS=$(date +%Y%m%d-%H%M%S); BNAME="vps-bill-pre-update-${OLD}-to-${NEW}-${TS}.db"; BACKUP="$BASE/backups/$BNAME"
mkdir -p "$BASE/backups"; chown 10001:10001 "$BASE/backups"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli backup --output "/app/backups/$BNAME" >/dev/null
[[ -s "$BACKUP" ]] || { echo "Backup не создан" >&2; exit 1; }

echo "[3/7] Проверяю миграцию на копии базы"
TEST="$TMP/testdb"; mkdir -p "$TEST"; cp "$BACKUP" "$TEST/billing.db"; chown -R 10001:10001 "$TEST"
docker run --rm --env-file "$ENV" -e DB_PATH=/test/billing.db -v "$TEST:/test" "vps-bill:$NEW" python -m app.cli migrate >/dev/null
docker run --rm --env-file "$ENV" -e DB_PATH=/test/billing.db -v "$TEST:/test" "vps-bill:$NEW" python -m app.cli db-check >/dev/null

echo "[4/7] Переключаю release"
docker compose -f "$COMPOSE" --env-file "$ENV" down >/dev/null
ln -sfn "releases/$NEW" "$BASE/current"
sed -i "s/^APP_VERSION=.*/APP_VERSION=$NEW/" "$ENV"

rollback(){
  trap - ERR
  echo "ОШИБКА: выполняю rollback $NEW -> $OLD" >&2
  docker compose -f "$COMPOSE" --env-file "$ENV" down >/dev/null 2>&1 || true
  rm -f "$BASE/data/billing.db" "$BASE/data/billing.db-wal" "$BASE/data/billing.db-shm"
  cp "$BACKUP" "$BASE/data/billing.db"; chown 10001:10001 "$BASE/data/billing.db"
  ln -sfn "releases/$OLD" "$BASE/current"
  sed -i "s/^APP_VERSION=.*/APP_VERSION=$OLD/" "$ENV"
  docker compose -f "$COMPOSE" --env-file "$ENV" up -d >/dev/null 2>&1 || true
  echo "Rollback завершён. Активна версия $OLD" >&2
}
trap 'rc=$?; if [[ $rc -ne 0 ]]; then rollback; fi; exit $rc' ERR

echo "[5/7] Мигрирую реальную базу"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli migrate >/dev/null

echo "[6/7] Запускаю новую версию"
docker compose -f "$COMPOSE" --env-file "$ENV" up -d >/dev/null

echo "[7/7] Health-check DB + Telegram"
PASS=0
for _ in $(seq 1 15); do
  if docker compose -f "$COMPOSE" --env-file "$ENV" exec -T bot python -m app.cli health --telegram --runtime >/tmp/vps-bill-update-health.log 2>&1; then PASS=1; break; fi
  sleep 2
done
[[ $PASS -eq 1 ]] || { cat /tmp/vps-bill-update-health.log >&2 || true; false; }
trap - ERR
cat /tmp/vps-bill-update-health.log
find "$BASE/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +5 | cut -d' ' -f2- | xargs -r rm -rf
# Чистим старые локальные backup: 30 дней / максимум 30 файлов.
find "$BASE/backups" -maxdepth 1 -type f \( -name 'vps-bill-*.db' -o -name 'vps-bill-*.tar.gz' \) -mtime +30 -delete || true
mapfile -t old_backups < <(find "$BASE/backups" -maxdepth 1 -type f \( -name 'vps-bill-*.db' -o -name 'vps-bill-*.tar.gz' \) -printf '%T@ %p\n' | sort -nr | tail -n +31 | cut -d' ' -f2-)
((${#old_backups[@]}==0)) || rm -f -- "${old_backups[@]}"
"$BASE/current/scripts/install-update-bridge.sh" >/dev/null 2>&1 || true
printf '✔ Обновлено: %s -> %s\nBackup: %s\n' "$OLD" "$NEW" "$BACKUP"
