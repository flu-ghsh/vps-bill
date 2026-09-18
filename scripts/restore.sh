#!/usr/bin/env bash
set -Eeuo pipefail
BASE=/opt/vps-bill; ENV="$BASE/.env"; COMPOSE="$BASE/compose.yaml"
mapfile -t FILES < <(find "$BASE/backups" -maxdepth 1 -type f -name '*.db' -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
((${#FILES[@]})) || { echo "Backup-файлы не найдены" >&2; exit 1; }
echo "Доступные backup:"; for i in "${!FILES[@]}"; do printf '%2d) %s\n' "$((i+1))" "$(basename "${FILES[$i]}")"; done
read -r -p "Выберите номер: " N </dev/tty
[[ "$N" =~ ^[0-9]+$ ]] && ((N>=1 && N<=${#FILES[@]})) || { echo "Неверный номер" >&2; exit 1; }
SRC="${FILES[$((N-1))]}"
read -r -p "Восстановить $(basename "$SRC")? [y/N]: " YES </dev/tty
[[ "$YES" =~ ^[YyДд]$ ]] || exit 0

docker compose -f "$COMPOSE" --env-file "$ENV" down
rm -f "$BASE/data/billing.db" "$BASE/data/billing.db-wal" "$BASE/data/billing.db-shm"
cp "$SRC" "$BASE/data/billing.db"; chown 10001:10001 "$BASE/data/billing.db"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli db-check
docker compose -f "$COMPOSE" --env-file "$ENV" up -d
echo "Восстановлено: $SRC"
