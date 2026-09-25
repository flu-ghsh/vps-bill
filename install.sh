#!/usr/bin/env bash
set -Eeuo pipefail

BASE="/opt/vps-bill"
ENV="$BASE/.env"
GITHUB_REPO="flu-ghsh/vps-bill"
RAW_BASE="https://raw.githubusercontent.com/$GITHUB_REPO/main"

c(){ printf '\033[1;36m%s\033[0m\n' "$*"; }
ok(){ printf '\033[1;32m✔\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m!\033[0m %s\n' "$*"; }
err(){ printf '\033[1;31m✖\033[0m %s\n' "$*" >&2; }

trim(){
  local v="$1"
  v="${v//$'\r'/}"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  printf '%s' "$v"
}

ask(){
  local __var="$1" prompt="$2" default="${3:-}" input=""
  if [[ -n "$default" ]]; then
    read -r -p "$prompt [$default]: " input </dev/tty || true
    input="${input:-$default}"
  else
    read -r -p "$prompt: " input </dev/tty || true
  fi
  printf -v "$__var" '%s' "$(trim "$input")"
}

secret(){
  local __var="$1" prompt="$2" input=""
  read -r -s -p "$prompt: " input </dev/tty || true
  printf '\n' >/dev/tty
  printf -v "$__var" '%s' "$(trim "$input")"
}

qenv(){
  python3 - "$1" <<'PY'
import json,sys
print(json.dumps(sys.argv[1], ensure_ascii=False))
PY
}

normalize_proxy(){
  local v
  v="$(trim "${1:-}")"
  [[ -n "$v" ]] || return 0
  case "$v" in
    socks5h://*) v="socks5://${v#socks5h://}" ;;
    *://*) ;;
    *) v="socks5://$v" ;;
  esac
  printf '%s' "$v"
}

[[ $EUID -eq 0 ]] || { err "Запустите от root"; exit 1; }

FRESH_INSTALL=0
if [[ -s "$BASE/data/billing.db" ]]; then
  FRESH_INSTALL=0
elif [[ -f "$ENV" || -L "$BASE/current" ]]; then
  err "Обнаружена существующая установка VPS Bill, но $BASE/data/billing.db отсутствует или пуста."
  err "Автоматическое создание новой пустой базы заблокировано. Сначала восстановите backup."
  exit 1
else
  FRESH_INSTALL=1
fi
ADD_DEMO=0

# Минимальные зависимости нужны ДО определения source:
# при bash <(curl ...) скрипт находится в /dev/fd и рядом нет VERSION/app.
apt-get update -qq
apt-get install -y -qq curl ca-certificates python3 util-linux tar gzip >/dev/null

SELF_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR=""
TMP_BOOTSTRAP=""

cleanup(){
  [[ -n "${TMP_BOOTSTRAP:-}" && -d "${TMP_BOOTSTRAP:-}" ]] && rm -rf "$TMP_BOOTSTRAP" || true
}
trap cleanup EXIT

# Локальный запуск из полноценного source/release дерева.
if [[ -f "$SELF_DIR/VERSION" && -d "$SELF_DIR/app" && -f "$SELF_DIR/Dockerfile" ]]; then
  SOURCE_DIR="$SELF_DIR"
  VERSION="$(tr -d '[:space:]' < "$SOURCE_DIR/VERSION")"
else
  # Bootstrap-режим для:
  # bash <(curl -fsSL https://raw.githubusercontent.com/flu-ghsh/vps-bill/main/install.sh)
  c "Загружаю VPS Bill из GitHub Release"

  VERSION="$(curl -fsSL "$RAW_BASE/VERSION" | tr -d '[:space:]')" || {
    err "Не удалось получить VERSION из GitHub"
    exit 1
  }

  [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
    err "GitHub вернул некорректный VERSION: $VERSION"
    exit 1
  }

  TMP_BOOTSTRAP="$(mktemp -d)"
  ARCHIVE="$TMP_BOOTSTRAP/vps-bill-$VERSION.tar.gz"
  RELEASE_URL="https://github.com/$GITHUB_REPO/releases/download/v$VERSION/vps-bill-$VERSION.tar.gz"
  CHECKSUM_URL="$RELEASE_URL.sha256"

  c "Скачиваю v$VERSION"
  CACHE_BUSTER="$(date +%s)"

  curl -fL --retry 3 --retry-delay 2 \
    -H 'Cache-Control: no-cache' \
    "${RELEASE_URL}?nocache=${CACHE_BUSTER}" \
    -o "$ARCHIVE" || {
      err "Не удалось скачать релиз v$VERSION"
      err "Ожидался asset:"
      err "$RELEASE_URL"
      exit 1
    }

  # Если checksum asset опубликован — проверяем. Если нет — установка всё равно возможна.
  if curl -fL --retry 2 --retry-delay 1 \
      -H 'Cache-Control: no-cache' \
      "${CHECKSUM_URL}?nocache=${CACHE_BUSTER}" \
      -o "$TMP_BOOTSTRAP/vps-bill-$VERSION.tar.gz.sha256" 2>/dev/null; then
    (
      cd "$TMP_BOOTSTRAP"
      sha256sum -c "vps-bill-$VERSION.tar.gz.sha256"
    ) || {
      err "SHA256 релиза не совпадает"
      exit 1
    }
    ok "SHA256 проверен"
  else
    warn "SHA256 asset не найден, пропускаю checksum-проверку"
  fi

  tar -xzf "$ARCHIVE" -C "$TMP_BOOTSTRAP"

  # Поддерживаем архив как с корневой папкой vps-bill-X.Y.Z/, так и без неё.
  if [[ -f "$TMP_BOOTSTRAP/vps-bill-$VERSION/VERSION" ]]; then
    SOURCE_DIR="$TMP_BOOTSTRAP/vps-bill-$VERSION"
  else
    SOURCE_DIR="$(find "$TMP_BOOTSTRAP" -mindepth 1 -maxdepth 2 -type f -name VERSION -printf '%h\n' | head -n1)"
  fi

  [[ -n "$SOURCE_DIR" && -d "$SOURCE_DIR/app" && -f "$SOURCE_DIR/Dockerfile" ]] || {
    err "В архиве релиза не найден корректный source tree"
    exit 1
  }

  ARCHIVE_VERSION="$(tr -d '[:space:]' < "$SOURCE_DIR/VERSION")"
  [[ "$ARCHIVE_VERSION" == "$VERSION" ]] || {
    err "VERSION в архиве ($ARCHIVE_VERSION) не совпадает с ожидаемой ($VERSION)"
    exit 1
  }

  ok "Релиз v$VERSION загружен"
fi

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  err "Некорректный VERSION: $VERSION"
  exit 1
}

RELEASE="$BASE/releases/$VERSION"

c "VPS Bill v$VERSION"

if ! command -v docker >/dev/null 2>&1; then
  c "Устанавливаю Docker Engine"
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh >/tmp/docker-install.log 2>&1 || {
    cat /tmp/docker-install.log
    exit 1
  }
fi

docker compose version >/dev/null 2>&1 || {
  err "Docker Compose plugin не найден"
  exit 1
}
ok "Docker готов"

mkdir -p \
  "$BASE" \
  "$BASE/data" \
  "$BASE/backups" \
  "$BASE/releases" \
  "$BASE/update-requests"

chown -R 10001:10001 "$BASE/data" "$BASE/backups" "$BASE/update-requests"
chmod 0770 "$BASE/update-requests"

# Полностью пересобираем только каталог этой версии.
rm -rf "$RELEASE"
mkdir -p "$RELEASE"

# Каталоги проекта.
for d in app scripts tests systemd docs; do
  if [[ -d "$SOURCE_DIR/$d" ]]; then
    cp -a "$SOURCE_DIR/$d" "$RELEASE/"
  fi
done

# Файлы проекта.
for f in \
  Dockerfile \
  requirements.txt \
  VERSION \
  CHANGELOG.md \
  README.md \
  .dockerignore \
  .env.example \
  install.sh \
  update.sh
do
  if [[ -f "$SOURCE_DIR/$f" ]]; then
    cp -aL "$SOURCE_DIR/$f" "$RELEASE/$f"
  fi
done

# compose.yaml может намеренно не храниться в git.
# Для runtime используем его, если он есть в release; иначе compose.example.yaml.
if [[ -f "$SOURCE_DIR/compose.yaml" ]]; then
  cp -aL "$SOURCE_DIR/compose.yaml" "$RELEASE/compose.yaml"
elif [[ -f "$SOURCE_DIR/compose.example.yaml" ]]; then
  cp -aL "$SOURCE_DIR/compose.example.yaml" "$RELEASE/compose.yaml"
else
  err "В релизе нет ни compose.yaml, ни compose.example.yaml"
  exit 1
fi

if [[ -f "$SOURCE_DIR/compose.example.yaml" ]]; then
  cp -aL "$SOURCE_DIR/compose.example.yaml" "$RELEASE/compose.example.yaml"
fi

[[ -d "$RELEASE/app" ]] || { err "В релизе отсутствует app/"; exit 1; }
[[ -f "$RELEASE/Dockerfile" ]] || { err "В релизе отсутствует Dockerfile"; exit 1; }
[[ -f "$RELEASE/requirements.txt" ]] || { err "В релизе отсутствует requirements.txt"; exit 1; }
[[ -f "$RELEASE/compose.yaml" ]] || { err "В релизе отсутствует compose.yaml"; exit 1; }

find "$RELEASE/scripts" -type f -name '*.sh' -exec chmod +x {} + 2>/dev/null || true
chmod +x "$RELEASE/install.sh" 2>/dev/null || true

# Существующий валидный .env сохраняем.
if [[ -f "$ENV" ]] && grep -q '^BOT_TOKEN=' "$ENV" && grep -q '^ADMIN_IDS=' "$ENV"; then
  c "Найден $ENV - сохраняю существующие настройки"
else
  BOT_TOKEN=""
  ADMIN_IDS=""
  TELEGRAM_PROXY=""
  TZ_VALUE=""
  UPDATE_MANIFEST_URL=""

  while [[ -z "$BOT_TOKEN" ]]; do
    secret BOT_TOKEN "BOT_TOKEN от @BotFather"
    [[ -n "$BOT_TOKEN" ]] || err "BOT_TOKEN не может быть пустым"
  done

  while [[ -z "$ADMIN_IDS" ]]; do
    ask ADMIN_IDS "Ваш Telegram numeric ID"
    [[ "$ADMIN_IDS" =~ ^[0-9]+([,;][0-9]+)*$ ]] || {
      err "Нужен numeric Telegram ID"
      ADMIN_IDS=""
    }
  done

  ask TELEGRAM_PROXY \
    "SOCKS5 для Telegram (например s5.example.com:1080; пусто = напрямую)" \
    ""
  TELEGRAM_PROXY="$(normalize_proxy "$TELEGRAM_PROXY")"

  SYS_TZ="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  SYS_TZ="${SYS_TZ:-Europe/Moscow}"
  ask TZ_VALUE "Timezone" "$SYS_TZ"

  ask UPDATE_MANIFEST_URL "URL manifest обновлений (можно пусто)" ""

  cat > "$ENV" <<EOF
APP_VERSION=$VERSION
BOT_TOKEN=$(qenv "$BOT_TOKEN")
ADMIN_IDS=$(qenv "$ADMIN_IDS")
TELEGRAM_PROXY=$(qenv "$TELEGRAM_PROXY")
TZ=$(qenv "$TZ_VALUE")
CHECK_INTERVAL_SECONDS=60
UPDATE_MANIFEST_URL=$(qenv "$UPDATE_MANIFEST_URL")
EOF

  chmod 600 "$ENV"
  ok "Конфигурация сохранена в $ENV"
fi

# Демоданные спрашиваем только на первой установке.
if [[ "$FRESH_INSTALL" -eq 1 ]]; then
  while true; do
    DEMO_ANSWER=""
    read -r -p "Добавить демо-серверы? [y/N]: " DEMO_ANSWER </dev/tty || true
    DEMO_ANSWER="$(printf '%s' "$DEMO_ANSWER" | tr '[:upper:]' '[:lower:]')"
    case "$DEMO_ANSWER" in
      y|yes|д|да) ADD_DEMO=1; break ;;
      n|no|н|нет|"") ADD_DEMO=0; break ;;
      *) warn "Введите y или n" ;;
    esac
  done
fi

# Старые/устаревшие env-параметры проекта не используем.
sed -i \
  '/^INFRA_BILLING_/d; /^REMINDER_DAYS=/d; /^MONTHLY_REPORT_ENABLED=/d; /^REPORT_HOUR=/d; /^EMOJI_.*_ID=/d' \
  "$ENV"

if grep -q '^APP_VERSION=' "$ENV"; then
  sed -i "s/^APP_VERSION=.*/APP_VERSION=$VERSION/" "$ENV"
else
  printf '\nAPP_VERSION=%s\n' "$VERSION" >> "$ENV"
fi

ensure_env(){
  local key="$1" value="$2"
  grep -q "^${key}=" "$ENV" || printf '%s=%s\n' "$key" "$value" >> "$ENV"
}

ensure_env TZ '"Europe/Moscow"'
ensure_env CHECK_INTERVAL_SECONDS '60'
ensure_env UPDATE_MANIFEST_URL '""'
ensure_env TELEGRAM_PROXY '""'
chmod 600 "$ENV"

c "Собираю Docker image vps-bill:$VERSION"
if ! docker build -t "vps-bill:$VERSION" "$RELEASE" >/tmp/vps-bill-build.log 2>&1; then
  cat /tmp/vps-bill-build.log
  err "Не удалось собрать Docker image"
  exit 1
fi
ok "Image собран"

ln -sfn "releases/$VERSION" "$BASE/current"

rm -f "$BASE/compose.yaml"
ln -s "current/compose.yaml" "$BASE/compose.yaml"

# Старый экспериментальный бот нельзя оставлять polling с тем же token.
if docker ps -a --format '{{.Names}}' | grep -qx 'vps-billing-bot'; then
  warn "Останавливаю старый контейнер vps-billing-bot"
  docker rm -f vps-billing-bot >/dev/null 2>&1 || true
fi

if docker ps -a --format '{{.Names}}' | grep -qx 'vps-bill'; then
  docker rm -f vps-bill >/dev/null 2>&1 || true
fi

c "Инициализирую базу"
docker compose \
  -f "$BASE/compose.yaml" \
  --env-file "$ENV" \
  run --rm bot python -m app.cli migrate \
  >/tmp/vps-bill-migrate.log

cat /tmp/vps-bill-migrate.log
touch "$BASE/data/.initialized"
chown 10001:10001 "$BASE/data/.initialized"
ok "База готова: $BASE/data/billing.db"

if [[ "$ADD_DEMO" -eq 1 ]]; then
  c "Добавляю демо-серверы"
  docker compose \
    -f "$BASE/compose.yaml" \
    --env-file "$ENV" \
    run --rm bot python -m app.cli demo-add \
    >/tmp/vps-bill-demo.log
  cat /tmp/vps-bill-demo.log
  ok "Демо-серверы добавлены"
fi

docker compose \
  -f "$BASE/compose.yaml" \
  --env-file "$ENV" \
  up -d

c "Проверяю Telegram"
PASS=0
for _ in $(seq 1 15); do
  if docker compose \
      -f "$BASE/compose.yaml" \
      --env-file "$ENV" \
      exec -T bot python -m app.cli health --telegram \
      >/tmp/vps-bill-health.log 2>&1; then
    PASS=1
    break
  fi
  sleep 2
done

if [[ $PASS -ne 1 ]]; then
  cat /tmp/vps-bill-health.log >&2 || true
  err "Health-check не пройден. Логи: docker logs vps-bill"
  exit 1
fi

cat /tmp/vps-bill-health.log
ok "Health-check пройден"

# Команды управления.
if [[ -f "$BASE/current/scripts/update.sh" ]]; then
  ln -sfn "$BASE/current/scripts/update.sh" /usr/local/bin/vps-bill-update
fi

if [[ -f "$BASE/current/scripts/backup.sh" ]]; then
  ln -sfn "$BASE/current/scripts/backup.sh" /usr/local/bin/vps-bill-backup
fi

if [[ -f "$BASE/current/scripts/restore.sh" ]]; then
  ln -sfn "$BASE/current/scripts/restore.sh" /usr/local/bin/vps-bill-restore
fi

# Удаляем старые имена, если они были symlink'ами старого проекта.
for old in billing-bot-update billing-bot-backup billing-bot-restore; do
  if [[ -L "/usr/local/bin/$old" ]]; then
    rm -f "/usr/local/bin/$old"
  fi
done

# Безопасный host-side update bridge для установки обновлений из Telegram.
if [[ -x "$BASE/current/scripts/install-update-bridge.sh" ]]; then
  c "Устанавливаю update bridge"
  "$BASE/current/scripts/install-update-bridge.sh"
  ok "Update bridge установлен"
fi

ok "VPS Bill v$VERSION установлен"

printf '\n'
printf 'Рабочая папка: %s\n' "$BASE"
printf 'Версия: %s\n' "$VERSION"
printf 'ENV: %s\n\n' "$ENV"
printf 'Команды:\n'
printf '  docker compose -f %s/compose.yaml --env-file %s/.env ps\n' "$BASE" "$BASE"
printf '  docker logs -f vps-bill\n'
printf '  vps-bill-backup\n'
printf '  vps-bill-restore\n'
printf '  vps-bill-update\n\n'
