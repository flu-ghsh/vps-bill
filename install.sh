#!/usr/bin/env bash

# VPS_BILL_REMOTE_BOOTSTRAP
# При запуске через curl/process substitution рядом со скриптом нет VERSION
# и остальных файлов проекта. В таком случае скачиваем весь репозиторий
# во временный каталог и запускаем локальную копию install.sh.
_VPS_BILL_SCRIPT="${BASH_SOURCE[0]:-}"
_VPS_BILL_DIR="$(cd -- "$(dirname -- "$_VPS_BILL_SCRIPT")" 2>/dev/null && pwd -P || true)"

if [[ -z "$_VPS_BILL_DIR" || ! -f "$_VPS_BILL_DIR/VERSION" ]]; then
    _VPS_BILL_TMP="$(mktemp -d)"

    _vps_bill_cleanup() {
        rm -rf "$_VPS_BILL_TMP"
    }
    trap _vps_bill_cleanup EXIT

    echo "▶ Загружаю VPS Bill с GitHub..."

    curl -fsSL \
        "https://github.com/flu-ghsh/vps-bill/archive/refs/heads/main.tar.gz" \
        | tar -xz -C "$_VPS_BILL_TMP" --strip-components=1

    if [[ ! -f "$_VPS_BILL_TMP/install.sh" ]]; then
        echo "✖ Не удалось загрузить установщик VPS Bill."
        exit 1
    fi

    bash "$_VPS_BILL_TMP/install.sh" "$@"
    exit $?
fi

set -Eeuo pipefail

BASE=/opt/vps-bill
SELF_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VERSION=$(tr -d '[:space:]' < "$SELF_DIR/VERSION")
RELEASE="$BASE/releases/$VERSION"
ENV="$BASE/.env"

c(){ printf '\033[1;36m%s\033[0m\n' "$*"; }
ok(){ printf '\033[1;32m✔\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m!\033[0m %s\n' "$*"; }
err(){ printf '\033[1;31m✖\033[0m %s\n' "$*" >&2; }
trim(){ local v="$1"; v="${v//$'\r'/}"; v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"; printf '%s' "$v"; }
ask(){ local __var="$1" prompt="$2" default="${3:-}" input=""; if [[ -n "$default" ]]; then read -r -p "$prompt [$default]: " input </dev/tty || true; input="${input:-$default}"; else read -r -p "$prompt: " input </dev/tty || true; fi; printf -v "$__var" '%s' "$(trim "$input")"; }
secret(){ local __var="$1" prompt="$2" input=""; read -r -s -p "$prompt: " input </dev/tty || true; printf '\n' >/dev/tty; printf -v "$__var" '%s' "$(trim "$input")"; }
qenv(){ python3 - "$1" <<'PY'
import json,sys
print(json.dumps(sys.argv[1], ensure_ascii=False))
PY
}
normalize_proxy(){ local v; v="$(trim "${1:-}")"; [[ -n "$v" ]] || return 0; case "$v" in socks5h://*) v="socks5://${v#socks5h://}";; *://*) ;; *) v="socks5://$v";; esac; printf '%s' "$v"; }

[[ $EUID -eq 0 ]] || { err "Запустите от root"; exit 1; }
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { err "Некорректный VERSION"; exit 1; }
c "VPS Bill v$VERSION"

apt-get update -qq
apt-get install -y -qq curl ca-certificates python3 util-linux >/dev/null
if ! command -v docker >/dev/null 2>&1; then
  c "Устанавливаю Docker Engine"
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  sh /tmp/get-docker.sh >/tmp/docker-install.log 2>&1 || { cat /tmp/docker-install.log; exit 1; }
fi
docker compose version >/dev/null 2>&1 || { err "Docker Compose plugin не найден"; exit 1; }
ok "Docker готов"

mkdir -p "$BASE" "$BASE/data" "$BASE/backups" "$BASE/releases" "$RELEASE"
chown -R 10001:10001 "$BASE/data" "$BASE/backups"

# Копируем только release-файлы; это безопасно даже когда install.sh запущен из /opt/vps-bill.
rm -rf "$RELEASE/app" "$RELEASE/scripts" "$RELEASE/tests"
cp -a "$SELF_DIR/app" "$SELF_DIR/scripts" "$SELF_DIR/tests" "$RELEASE/"
cp -aL "$SELF_DIR/Dockerfile" "$SELF_DIR/requirements.txt" "$SELF_DIR/VERSION" "$SELF_DIR/.dockerignore" "$SELF_DIR/.env.example" "$SELF_DIR/README.md" "$SELF_DIR/install.sh" "$RELEASE/"
cp -aL "$SELF_DIR/compose.example.yaml" "$RELEASE/compose.yaml"
chmod +x "$RELEASE/scripts"/*.sh

# Существующий валидный .env сохраняем. Пустой/старый env пересоздаём.
if [[ -f "$ENV" ]] && grep -q '^BOT_TOKEN=' "$ENV" && grep -q '^ADMIN_IDS=' "$ENV"; then
  c "Найден $ENV — сохраняю существующие настройки"
else
  BOT_TOKEN=""; ADMIN_IDS=""; TELEGRAM_PROXY=""; TZ_VALUE=""; UPDATE_MANIFEST_URL=""
  while [[ -z "$BOT_TOKEN" ]]; do secret BOT_TOKEN "BOT_TOKEN от @BotFather"; [[ -n "$BOT_TOKEN" ]] || err "BOT_TOKEN не может быть пустым"; done
  while [[ -z "$ADMIN_IDS" ]]; do ask ADMIN_IDS "Ваш Telegram numeric ID"; [[ "$ADMIN_IDS" =~ ^[0-9]+([,;][0-9]+)*$ ]] || { err "Нужен numeric Telegram ID"; ADMIN_IDS=""; }; done
  ask TELEGRAM_PROXY "SOCKS5 для Telegram (например s5.example.com:1080; пусто = напрямую)" ""
  TELEGRAM_PROXY="$(normalize_proxy "$TELEGRAM_PROXY")"
  SYS_TZ=$(timedatectl show -p Timezone --value 2>/dev/null || true); SYS_TZ=${SYS_TZ:-Europe/Moscow}
  ask TZ_VALUE "Timezone" "$SYS_TZ"
  ask UPDATE_MANIFEST_URL "URL manifest обновлений (можно пусто)" ""
  cat > "$ENV" <<EOF
APP_VERSION=$VERSION
BOT_TOKEN=$(qenv "$BOT_TOKEN")
ADMIN_IDS=$(qenv "$ADMIN_IDS")
TELEGRAM_PROXY=$(qenv "$TELEGRAM_PROXY")
TZ=$(qenv "$TZ_VALUE")
CHECK_INTERVAL_SECONDS=60
REMINDER_DAYS="7,3,1,0"
MONTHLY_REPORT_ENABLED=true
REPORT_HOUR=10
UPDATE_MANIFEST_URL=$(qenv "$UPDATE_MANIFEST_URL")
EMOJI_MONEY_ID=""
EMOJI_SERVER_ID=""
EMOJI_CHART_ID=""
EMOJI_CALENDAR_ID=""
EMOJI_SETTINGS_ID=""
EMOJI_OK_ID=""
EMOJI_WARNING_ID=""
EOF
  chmod 600 "$ENV"
  ok "Конфигурация сохранена в $ENV"
fi

# Убираем ключи старого экспериментального Infra Billing — v2 их не использует.
sed -i '/^INFRA_BILLING_/d' "$ENV"
if grep -q '^APP_VERSION=' "$ENV"; then sed -i "s/^APP_VERSION=.*/APP_VERSION=$VERSION/" "$ENV"; else printf '\nAPP_VERSION=%s\n' "$VERSION" >> "$ENV"; fi
ensure_env(){ local key="$1" value="$2"; grep -q "^${key}=" "$ENV" || printf '%s=%s\n' "$key" "$value" >> "$ENV"; }
ensure_env TZ '"Europe/Moscow"'
ensure_env CHECK_INTERVAL_SECONDS '60'
ensure_env REMINDER_DAYS '"7,3,1,0"'
ensure_env MONTHLY_REPORT_ENABLED 'true'
ensure_env REPORT_HOUR '10'
ensure_env UPDATE_MANIFEST_URL '""'
ensure_env TELEGRAM_PROXY '""'
chmod 600 "$ENV"

c "Собираю Docker image vps-bill:$VERSION"
docker build -t "vps-bill:$VERSION" "$RELEASE" >/tmp/vps-bill-build.log 2>&1 || { cat /tmp/vps-bill-build.log; exit 1; }
ok "Image собран"

ln -sfn "releases/$VERSION" "$BASE/current"
rm -f "$BASE/compose.yaml"
ln -s "current/compose.yaml" "$BASE/compose.yaml"

# Старый экспериментальный бот нельзя оставлять polling с тем же token.
if docker ps -a --format '{{.Names}}' | grep -qx 'vps-billing-bot'; then
  warn "Останавливаю старый контейнер vps-billing-bot (файлы /opt/vps-billing-bot не удаляются)"
  docker rm -f vps-billing-bot >/dev/null 2>&1 || true
fi
if docker ps -a --format '{{.Names}}' | grep -qx 'vps-bill'; then docker rm -f vps-bill >/dev/null 2>&1 || true; fi

c "Инициализирую собственную базу"
docker compose -f "$BASE/compose.yaml" --env-file "$ENV" run --rm bot python -m app.cli migrate >/tmp/vps-bill-migrate.log
cat /tmp/vps-bill-migrate.log
ok "База готова: $BASE/data/billing.db"

docker compose -f "$BASE/compose.yaml" --env-file "$ENV" up -d

c "Проверяю Telegram через SOCKS5"
PASS=0
for _ in $(seq 1 15); do
  if docker compose -f "$BASE/compose.yaml" --env-file "$ENV" exec -T bot python -m app.cli health --telegram >/tmp/vps-bill-health.log 2>&1; then PASS=1; break; fi
  sleep 2
done
if [[ $PASS -ne 1 ]]; then
  cat /tmp/vps-bill-health.log >&2 || true
  err "Health-check не пройден. Логи: docker logs vps-bill"
  exit 1
fi
cat /tmp/vps-bill-health.log

ln -sfn "$BASE/current/scripts/update.sh" /usr/local/bin/vps-bill-update
ln -sfn "$BASE/current/scripts/backup.sh" /usr/local/bin/vps-bill-backup
ln -sfn "$BASE/current/scripts/restore.sh" /usr/local/bin/vps-bill-restore

# Удаляем старые имена команд, если остались от прежних версий.
rm -f   /usr/local/bin/vps-bill-update   /usr/local/bin/vps-bill-backup   /usr/local/bin/vps-bill-restore

ok "VPS Bill установлен"
printf '\nРабочая папка: %s\nENV: %s\n\nКоманды:\n  docker compose -f %s/compose.yaml --env-file %s/.env ps\n  docker logs -f vps-bill\n  vps-bill-backup\n  vps-bill-restore\n  vps-bill-update --file <release.tar.gz>\n\n' "$BASE" "$ENV" "$BASE" "$BASE"
