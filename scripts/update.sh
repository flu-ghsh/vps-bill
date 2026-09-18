#!/usr/bin/env bash
set -Eeuo pipefail

BASE="/opt/vps-bill"
ENV="$BASE/.env"
COMPOSE="$BASE/compose.yaml"
RELEASES="$BASE/releases"
BACKUPS="$BASE/backups"
DB="$BASE/data/billing.db"

GITHUB_REPO="flu-ghsh/vps-bill"
GITHUB_API="https://api.github.com/repos/$GITHUB_REPO"

LOCK="/var/lock/vps-bill-update.lock"

c(){ printf '\033[1;36m%s\033[0m\n' "$*"; }
ok(){ printf '\033[1;32m✔\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m!\033[0m %s\n' "$*"; }
err(){ printf '\033[1;31m✖\033[0m %s\n' "$*" >&2; }

[[ $EUID -eq 0 ]] || {
  err "Запустите обновление от root."
  exit 1
}

command -v curl >/dev/null || {
  err "Не найден curl."
  exit 1
}

command -v docker >/dev/null || {
  err "Не найден Docker."
  exit 1
}

command -v python3 >/dev/null || {
  err "Не найден python3."
  exit 1
}

mkdir -p "$RELEASES" "$BACKUPS"

exec 9>"$LOCK"
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || {
    err "Обновление VPS Bill уже выполняется."
    exit 1
  }
fi

if [[ -f "$BASE/current/VERSION" ]]; then
  CURRENT="$(tr -d '[:space:]' < "$BASE/current/VERSION")"
elif [[ -f "$BASE/VERSION" ]]; then
  CURRENT="$(tr -d '[:space:]' < "$BASE/VERSION")"
else
  err "Не удалось определить установленную версию."
  exit 1
fi

c "VPS Bill v$CURRENT"
c "Проверяю последний GitHub Release..."

RELEASE_JSON="$(
  curl -fsSL \
    -H "Accept: application/vnd.github+json" \
    -H "User-Agent: VPS-Bill-Updater" \
    "$GITHUB_API/releases/latest"
)" || {
  err "Не удалось получить информацию о последнем GitHub Release."
  exit 1
}

TAG="$(
  printf '%s' "$RELEASE_JSON" |
    python3 -c '
import json,sys
data=json.load(sys.stdin)
print(data.get("tag_name",""))
'
)"

[[ -n "$TAG" ]] || {
  err "GitHub не вернул tag_name последнего релиза."
  exit 1
}

NEW="${TAG#v}"

printf 'Текущая версия : %s\n' "$CURRENT"
printf 'Последняя версия: %s\n' "$NEW"

if [[ "$CURRENT" == "$NEW" ]]; then
  ok "Установлена последняя версия VPS Bill."
  exit 0
fi

# Не допускаем автоматический downgrade.
LATEST_SORTED="$(printf '%s\n%s\n' "$CURRENT" "$NEW" | sort -V | tail -1)"
if [[ "$LATEST_SORTED" != "$NEW" ]]; then
  warn "Установленная версия $CURRENT новее опубликованного релиза $NEW."
  exit 0
fi

TMP="$(mktemp -d /tmp/vps-bill-update.XXXXXX)"
cleanup(){ rm -rf "$TMP"; }
trap cleanup EXIT

SRC="$TMP/src"
mkdir -p "$SRC"

URL="https://github.com/$GITHUB_REPO/archive/refs/tags/$TAG.tar.gz"

c "Скачиваю VPS Bill $TAG..."

curl -fL --retry 3 --connect-timeout 15 \
  "$URL" |
  tar -xz -C "$SRC" --strip-components=1

[[ -f "$SRC/VERSION" ]] || {
  err "В релизе отсутствует VERSION."
  exit 1
}

DOWNLOADED="$(tr -d '[:space:]' < "$SRC/VERSION")"

if [[ "$DOWNLOADED" != "$NEW" ]]; then
  err "Версия релиза не совпадает: tag=$NEW, VERSION=$DOWNLOADED"
  exit 1
fi

for f in Dockerfile requirements.txt compose.example.yaml; do
  [[ -f "$SRC/$f" ]] || {
    err "В релизе отсутствует $f"
    exit 1
  }
done

TARGET="$RELEASES/$NEW"

if [[ -e "$TARGET" ]]; then
  warn "Каталог $TARGET уже существует — пересоздаю."
  rm -rf "$TARGET"
fi

mkdir -p "$TARGET"

cp -a "$SRC/app" "$TARGET/"
cp -a "$SRC/scripts" "$TARGET/"

[[ -d "$SRC/tests" ]] && cp -a "$SRC/tests" "$TARGET/"

cp -aL "$SRC/Dockerfile" "$TARGET/Dockerfile"
cp -aL "$SRC/requirements.txt" "$TARGET/requirements.txt"
cp -aL "$SRC/VERSION" "$TARGET/VERSION"
cp -aL "$SRC/compose.example.yaml" "$TARGET/compose.yaml"

[[ -f "$SRC/.dockerignore" ]] &&
  cp -aL "$SRC/.dockerignore" "$TARGET/.dockerignore"

[[ -f "$SRC/.env.example" ]] &&
  cp -aL "$SRC/.env.example" "$TARGET/.env.example"

[[ -f "$SRC/README.md" ]] &&
  cp -aL "$SRC/README.md" "$TARGET/README.md"

chmod +x "$TARGET/scripts/"*.sh 2>/dev/null || true

c "Собираю Docker image vps-bill:$NEW"

docker build \
  -t "vps-bill:$NEW" \
  "$TARGET" \
  >/tmp/vps-bill-update-build.log 2>&1 || {
    cat /tmp/vps-bill-update-build.log >&2
    err "Не удалось собрать Docker image."
    exit 1
  }

ok "Image vps-bill:$NEW собран"

STAMP="$(date +%Y%m%d-%H%M%S)"
DB_BACKUP="$BACKUPS/pre-update-${CURRENT}-to-${NEW}-${STAMP}.db"
ENV_BACKUP="$TMP/env.before"
OLD_CURRENT="$(readlink -f "$BASE/current" 2>/dev/null || true)"

cp -a "$ENV" "$ENV_BACKUP"

c "Останавливаю текущую версию..."
docker compose \
  -f "$COMPOSE" \
  --env-file "$ENV" \
  down >/dev/null

if [[ -f "$DB" ]]; then
  c "Создаю резервную копию базы..."

  python3 - "$DB" "$DB_BACKUP" <<'PY'
import sqlite3
import sys

src_path, dst_path = sys.argv[1], sys.argv[2]

src = sqlite3.connect(src_path)
dst = sqlite3.connect(dst_path)

try:
    src.backup(dst)
finally:
    dst.close()
    src.close()
PY

  chown --reference="$DB" "$DB_BACKUP" 2>/dev/null || true
  ok "Backup: $DB_BACKUP"
fi

set_env_version() {
  local ver="$1"

  python3 - "$ENV" "$ver" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
version = sys.argv[2]

lines = path.read_text().splitlines()
out = []
found = False

for line in lines:
    if line.startswith("APP_VERSION="):
        out.append(f"APP_VERSION={version}")
        found = True
    else:
        out.append(line)

if not found:
    out.insert(0, f"APP_VERSION={version}")

path.write_text("\n".join(out) + "\n")
PY
}

rollback() {
  err "Обновление не удалось. Выполняю rollback..."

  docker compose \
    -f "$COMPOSE" \
    --env-file "$ENV" \
    down >/dev/null 2>&1 || true

  if [[ -n "$OLD_CURRENT" && -d "$OLD_CURRENT" ]]; then
    ln -sfn "releases/$(basename "$OLD_CURRENT")" "$BASE/current"
  fi

  cp -a "$ENV_BACKUP" "$ENV"

  if [[ -f "$DB_BACKUP" ]]; then
    cp -a "$DB_BACKUP" "$DB"
    chown 10001:10001 "$DB" 2>/dev/null || true
  fi

  docker compose \
    -f "$COMPOSE" \
    --env-file "$ENV" \
    up -d >/dev/null 2>&1 || true

  err "Возвращена VPS Bill v$CURRENT"
}

set_env_version "$NEW"
ln -sfn "releases/$NEW" "$BASE/current"

c "Выполняю миграцию базы..."

if ! docker compose \
  -f "$COMPOSE" \
  --env-file "$ENV" \
  run --rm bot python -m app.cli migrate \
  >/tmp/vps-bill-update-migrate.log 2>&1
then
  cat /tmp/vps-bill-update-migrate.log >&2 || true
  rollback
  exit 1
fi

cat /tmp/vps-bill-update-migrate.log

c "Запускаю VPS Bill $NEW..."

if ! docker compose \
  -f "$COMPOSE" \
  --env-file "$ENV" \
  up -d
then
  rollback
  exit 1
fi

c "Проверяю работу контейнера..."

PASS=0

for _ in $(seq 1 10); do
  if docker compose \
      -f "$COMPOSE" \
      --env-file "$ENV" \
      exec -T bot python -m app.cli health --runtime \
      >/tmp/vps-bill-update-health.log 2>&1
  then
    PASS=1
    break
  fi

  sleep 2
done

if [[ $PASS -ne 1 ]]; then
  cat /tmp/vps-bill-update-health.log >&2 || true
  rollback
  exit 1
fi

cat /tmp/vps-bill-update-health.log

ln -sfn "$BASE/current/scripts/update.sh" /usr/local/bin/vps-bill-update
ln -sfn "$BASE/current/scripts/backup.sh" /usr/local/bin/vps-bill-backup
ln -sfn "$BASE/current/scripts/restore.sh" /usr/local/bin/vps-bill-restore

hash -r 2>/dev/null || true

ok "VPS Bill обновлён: $CURRENT → $NEW"
