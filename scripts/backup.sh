#!/usr/bin/env bash
set -Eeuo pipefail
BASE=/opt/vps-bill; ENV="$BASE/.env"; COMPOSE="$BASE/compose.yaml"
[[ -f "$ENV" ]] || { echo "Нет $ENV" >&2; exit 1; }
mkdir -p "$BASE/backups"; chown 10001:10001 "$BASE/backups"
NAME="vps-bill-$(date +%Y%m%d-%H%M%S).db"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli backup --output "/app/backups/$NAME"
echo "Backup: $BASE/backups/$NAME"
# Политика по умолчанию: не старше 30 дней и максимум 30 локальных копий.
find "$BASE/backups" -maxdepth 1 -type f \( -name 'vps-bill-*.db' -o -name 'vps-bill-*.tar.gz' \) -mtime +30 -delete || true
mapfile -t old < <(find "$BASE/backups" -maxdepth 1 -type f \( -name 'vps-bill-*.db' -o -name 'vps-bill-*.tar.gz' \) -printf '%T@ %p\n' | sort -nr | tail -n +31 | cut -d' ' -f2-)
((${#old[@]}==0)) || rm -f -- "${old[@]}"
