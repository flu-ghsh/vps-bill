#!/usr/bin/env bash
set -Eeuo pipefail
BASE=/opt/vps-bill; ENV="$BASE/.env"; COMPOSE="$BASE/compose.yaml"
[[ -f "$ENV" ]] || { echo "Нет $ENV" >&2; exit 1; }
mkdir -p "$BASE/backups"; chown 10001:10001 "$BASE/backups"
NAME="billing-$(date +%Y%m%d-%H%M%S).db"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli backup --output "/app/backups/$NAME"
echo "Backup: $BASE/backups/$NAME"
find "$BASE/backups" -maxdepth 1 -type f -name 'billing-*.db' -mtime +30 -delete || true
