#!/usr/bin/env bash
set -Eeuo pipefail
BASE=/opt/vps-bill; ENV="$BASE/.env"; COMPOSE="$BASE/compose.yaml"
[[ -f "$ENV" ]] || { echo "Нет $ENV" >&2; exit 1; }
DB="$BASE/data/billing.db"
[[ -s "$DB" ]] || { echo "КРИТИЧЕСКАЯ ОШИБКА: $DB отсутствует или пуста" >&2; exit 1; }
python3 - "$DB" <<'PYDBCHECK'
import sqlite3,sys
p=sys.argv[1]
con=sqlite3.connect(f"file:{p}?mode=ro", uri=True)
r=con.execute("PRAGMA quick_check").fetchone(); con.close()
if not r or r[0] != "ok": raise SystemExit(f"SQLite quick_check: {r[0] if r else 'no result'}")
PYDBCHECK
mkdir -p "$BASE/backups"; chown 10001:10001 "$BASE/backups"
NAME="vps-bill-$(date +%Y%m%d-%H%M%S).db"
docker compose -f "$COMPOSE" --env-file "$ENV" run --rm bot python -m app.cli backup --output "/app/backups/$NAME"
echo "Backup: $BASE/backups/$NAME"
# Политика по умолчанию: не старше 30 дней и максимум 30 локальных копий.
find "$BASE/backups" -maxdepth 1 -type f \( -name 'vps-bill-*.db' -o -name 'vps-bill-*.tar.gz' \) -mtime +30 -delete || true
mapfile -t old < <(find "$BASE/backups" -maxdepth 1 -type f \( -name 'vps-bill-*.db' -o -name 'vps-bill-*.tar.gz' \) -printf '%T@ %p\n' | sort -nr | tail -n +31 | cut -d' ' -f2-)
((${#old[@]}==0)) || rm -f -- "${old[@]}"
