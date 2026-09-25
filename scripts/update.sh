#!/usr/bin/env bash
set -Eeuo pipefail

BASE=/opt/vps-bill
ENV="$BASE/.env"
COMPOSE="$BASE/compose.yaml"
LOCK=/var/lock/vps-bill-update.lock
REPO_DEFAULT="flu-ghsh/vps-bill"
REPO="${VPS_BILL_GITHUB_REPO:-$REPO_DEFAULT}"

exec 9>"$LOCK"
flock -n 9 || { echo "Обновление уже выполняется" >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Запустите от root" >&2; exit 1; }
[[ -f "$ENV" && -L "$BASE/current" ]] || { echo "VPS Bill не установлен" >&2; exit 1; }

# Repair writable runtime directories before any new container is started.
# This also heals installations upgraded from releases where update-requests
# was accidentally root-owned.
mkdir -p "$BASE/data" "$BASE/backups" "$BASE/update-downloads"
install -d -o 10001 -g 10001 -m 0770 "$BASE/update-requests"
chown 10001:10001 "$BASE/update-requests"
chmod 0770 "$BASE/update-requests"
rm -f "$BASE/update-requests/.request.json.tmp" 2>/dev/null || true
find "$BASE/update-requests" -maxdepth 1 -type f -name '.request.*.tmp' -delete 2>/dev/null || true

usage(){
  echo "Использование: vps-bill-update [--file release.tar.gz|--manifest URL|--github]" >&2
}

normalize_version(){
  local v="${1:-}"
  v="${v//[$'\t\r\n ']/}"
  v="${v#refs/tags/}"
  v="${v#V}"
  v="${v#v}"
  v="${v#.}"
  if [[ ! "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    return 1
  fi
  printf '%s\n' "$v"
}

version_cmp(){
  # Prints: -1 when $1 < $2, 0 when equal, 1 when $1 > $2.
  python3 - "$1" "$2" <<'PY'
import sys

def parse(v):
    return tuple(int(x) for x in v.split('.'))
a,b=map(parse,sys.argv[1:3])
print((a>b)-(a<b))
PY
}

FILE=""
MANIFEST_ARG=""
MODE="github"
case "${1:-}" in
  --file)
    [[ -n "${2:-}" ]] || { usage; exit 2; }
    FILE="$2"; MODE="file"
    ;;
  --manifest)
    [[ -n "${2:-}" ]] || { usage; exit 2; }
    MANIFEST_ARG="$2"; MODE="manifest"
    ;;
  --github|"") MODE="github" ;;
  *) usage; exit 2 ;;
esac

TMP=$(mktemp -d /tmp/vps-bill-update.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
OLD_RAW=$(tr -d '[:space:]' < "$BASE/current/VERSION")
OLD=$(normalize_version "$OLD_RAW") || { echo "Некорректная текущая версия: $OLD_RAW" >&2; exit 1; }

if [[ "$MODE" == "github" ]]; then
  echo "VPS Bill v$OLD"
  echo "Проверяю последний GitHub Release..."
  API="$TMP/latest.json"
  curl -fsSL \
    -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: VPS-Bill-Updater' \
    -H 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/$REPO/releases/latest" -o "$API"

  readarray -t META < <(python3 - "$API" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
print(str(obj.get('tag_name') or '').strip())
print(str(obj.get('name') or '').strip())
for a in obj.get('assets') or []:
    print('ASSET\t'+str(a.get('name') or '')+'\t'+str(a.get('browser_download_url') or '')+'\t'+str(a.get('digest') or ''))
PY
  )
  TAG_RAW="${META[0]:-}"
  NEW=$(normalize_version "$TAG_RAW") || {
    echo "Некорректный tag GitHub Release: '$TAG_RAW'" >&2
    exit 1
  }

  printf 'Текущая версия : %s\nПоследняя версия: %s\n' "$OLD" "$NEW"
  CMP=$(version_cmp "$OLD" "$NEW")
  if [[ "$CMP" == "0" ]]; then
    echo "Уже установлена последняя версия $OLD"
    exit 0
  elif [[ "$CMP" == "1" ]]; then
    echo "! Установленная версия $OLD новее опубликованного релиза $NEW."
    exit 0
  fi

  WANTED="vps-bill-$NEW.tar.gz"
  URL=""; DIGEST=""; CHECKSUM_URL=""
  for line in "${META[@]:2}"; do
    IFS=$'\t' read -r kind name url digest <<<"$line"
    [[ "$kind" == "ASSET" ]] || continue
    if [[ "$name" == "$WANTED" ]]; then URL="$url"; DIGEST="$digest"; fi
    if [[ "$name" == "$WANTED.sha256" || "$name" == "SHA256SUMS" ]]; then CHECKSUM_URL="$url"; fi
  done
  [[ -n "$URL" ]] || { echo "В GitHub Release не найден файл $WANTED" >&2; exit 1; }
  [[ "$URL" == https://github.com/*/releases/download/* ]] || { echo "Некорректный URL release asset" >&2; exit 1; }

  FILE="$TMP/$WANTED"
  echo "Скачиваю $WANTED"
  curl -fL "$URL" -o "$FILE"

  EXPECTED=""
  if [[ "$DIGEST" == sha256:* ]]; then
    EXPECTED="${DIGEST#sha256:}"
  elif [[ -n "$CHECKSUM_URL" ]]; then
    CS="$TMP/checksum.txt"
    curl -fsSL "$CHECKSUM_URL" -o "$CS"
    EXPECTED=$(python3 - "$CS" "$WANTED" <<'PY'
import re,sys
text=open(sys.argv[1],encoding='utf-8',errors='replace').read(); name=sys.argv[2]
for line in text.splitlines():
    m=re.match(r'^([0-9a-fA-F]{64})\s+\*?(.+)$',line.strip())
    if m and m.group(2).strip().split('/')[-1] == name:
        print(m.group(1).lower()); break
PY
    )
  fi
  if [[ -n "$EXPECTED" ]]; then
    ACTUAL=$(sha256sum "$FILE" | awk '{print $1}')
    [[ "$ACTUAL" == "$EXPECTED" ]] || { echo "SHA256 не совпал" >&2; exit 1; }
    echo "SHA256: OK"
  else
    echo "! У release нет SHA256 asset/digest; продолжаю после проверки структуры архива."
  fi
fi

if [[ "$MODE" == "manifest" ]]; then
  MANIFEST="$MANIFEST_ARG"
  if [[ -z "$MANIFEST" ]]; then
    MANIFEST=$(grep '^UPDATE_MANIFEST_URL=' "$ENV" | head -1 | cut -d= -f2- | sed 's/^"//;s/"$//' || true)
  fi
  [[ -n "$MANIFEST" ]] || { echo "UPDATE_MANIFEST_URL пуст" >&2; exit 1; }
  echo "Получаю manifest: $MANIFEST"
  curl -fsSL "$MANIFEST" -o "$TMP/latest.json"
  URL=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["url"])' "$TMP/latest.json")
  SHA=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("sha256", ""))' "$TMP/latest.json")
  FILE="$TMP/release.tar.gz"
  curl -fL "$URL" -o "$FILE"
  if [[ -n "$SHA" ]]; then
    echo "$SHA  $FILE" | sha256sum -c - >/dev/null || { echo "SHA256 не совпал" >&2; exit 1; }
  fi
fi

[[ -f "$FILE" ]] || { echo "Файл не найден: $FILE" >&2; exit 1; }

tar -xzf "$FILE" -C "$TMP"
VF=$(find "$TMP" -maxdepth 4 -type f -name VERSION | head -1)
[[ -n "$VF" ]] || { echo "VERSION не найден в release" >&2; exit 1; }
SRC=$(dirname "$VF")
NEW_RAW=$(tr -d '[:space:]' < "$VF")
NEW=$(normalize_version "$NEW_RAW") || { echo "Некорректная версия release: $NEW_RAW" >&2; exit 1; }
[[ -f "$SRC/Dockerfile" && -f "$SRC/compose.yaml" && -d "$SRC/app" ]] || { echo "Неполный release" >&2; exit 1; }

if [[ "$MODE" == "github" && "$NEW" != "$(normalize_version "$TAG_RAW")" ]]; then
  echo "Версия в архиве ($NEW) не совпадает с GitHub tag ($TAG_RAW)" >&2
  exit 1
fi

CMP=$(version_cmp "$OLD" "$NEW")
if [[ "$CMP" == "0" ]]; then
  echo "Уже установлена версия $NEW"
  exit 0
elif [[ "$CMP" == "1" ]]; then
  echo "Установленная версия $OLD новее release $NEW. Для downgrade используйте ручное восстановление/релиз." >&2
  exit 1
fi

echo "Обновление $OLD -> $NEW"
TARGET="$BASE/releases/$NEW"
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -a "$SRC"/. "$TARGET"/
chmod +x "$TARGET/scripts"/*.sh

# Keep the runtime compose file in /opt/vps-bill in sync with the release.
# Older updaters left this file behind, which could preserve stale mounts.
cp -f "$TARGET/compose.yaml" "$BASE/compose.yaml"

# Repair/update the host-side Telegram update bridge on every release.
if [[ -x "$TARGET/scripts/install-update-bridge.sh" ]]; then
  "$TARGET/scripts/install-update-bridge.sh" >/dev/null
fi

echo "[1/7] Собираю новый image, старый бот продолжает работать"
docker build -t "vps-bill:$NEW" "$TARGET" >/tmp/vps-bill-update-build.log 2>&1 || { cat /tmp/vps-bill-update-build.log; exit 1; }

echo "[2/7] Создаю online backup"
TS=$(date +%Y%m%d-%H%M%S)
BNAME="vps-bill-pre-update-${OLD}-to-${NEW}-${TS}.db"
BACKUP="$BASE/backups/$BNAME"
mkdir -p "$BASE/backups"
chown 10001:10001 "$BASE/backups"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli backup --output "/app/backups/$BNAME" >/dev/null
[[ -s "$BACKUP" ]] || { echo "Backup не создан" >&2; exit 1; }

echo "[3/7] Проверяю миграцию на копии базы"
TEST="$TMP/testdb"
mkdir -p "$TEST"
cp "$BACKUP" "$TEST/billing.db"
chown -R 10001:10001 "$TEST"
docker run --rm --env-file "$ENV" -e DB_PATH=/test/billing.db -v "$TEST:/test" "vps-bill:$NEW" python -m app.cli migrate >/dev/null
docker run --rm --env-file "$ENV" -e DB_PATH=/test/billing.db -v "$TEST:/test" "vps-bill:$NEW" python -m app.cli db-check >/dev/null

echo "[4/7] Переключаю release"
docker compose -f "$COMPOSE" --env-file "$ENV" down >/dev/null
ln -sfn "releases/$NEW" "$BASE/current"
if grep -q '^APP_VERSION=' "$ENV"; then
  sed -i "s/^APP_VERSION=.*/APP_VERSION=$NEW/" "$ENV"
else
  printf '\nAPP_VERSION=%s\n' "$NEW" >> "$ENV"
fi

rollback(){
  trap - ERR
  echo "ОШИБКА: выполняю rollback $NEW -> $OLD" >&2
  docker compose -f "$COMPOSE" --env-file "$ENV" down >/dev/null 2>&1 || true
  rm -f "$BASE/data/billing.db" "$BASE/data/billing.db-wal" "$BASE/data/billing.db-shm"
  cp "$BACKUP" "$BASE/data/billing.db"
  chown 10001:10001 "$BASE/data/billing.db"
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
for _ in $(seq 1 20); do
  if docker compose -f "$COMPOSE" --env-file "$ENV" exec -T bot python -m app.cli health --telegram --runtime >/tmp/vps-bill-update-health.log 2>&1; then
    PASS=1
    break
  fi
  sleep 2
done
[[ $PASS -eq 1 ]] || { cat /tmp/vps-bill-update-health.log >&2 || true; false; }
trap - ERR
cat /tmp/vps-bill-update-health.log

find "$BASE/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +5 | cut -d' ' -f2- | xargs -r rm -rf
find "$BASE/backups" -maxdepth 1 -type f \( -name 'vps-bill-*.db' -o -name 'vps-bill-*.tar.gz' \) -mtime +30 -delete || true
mapfile -t old_backups < <(find "$BASE/backups" -maxdepth 1 -type f \( -name 'vps-bill-*.db' -o -name 'vps-bill-*.tar.gz' \) -printf '%T@ %p\n' | sort -nr | tail -n +31 | cut -d' ' -f2-)
((${#old_backups[@]}==0)) || rm -f -- "${old_backups[@]}"
"$BASE/current/scripts/install-update-bridge.sh" >/dev/null 2>&1 || true

printf '✔ Обновлено: %s -> %s\nBackup: %s\n' "$OLD" "$NEW" "$BACKUP"
