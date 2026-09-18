#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd); VER=$(tr -d '[:space:]' < "$ROOT/VERSION")
OUT="$ROOT/release"; TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
NAME="vps-bill-$VER"; mkdir -p "$TMP/$NAME"
for x in app scripts tests Dockerfile requirements.txt VERSION compose.yaml install.sh README.md .dockerignore .env.example; do cp -a "$ROOT/$x" "$TMP/$NAME/"; done
find "$TMP/$NAME" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$TMP/$NAME" -type f -name "*.py[co]" -delete
mkdir -p "$OUT"; tar -C "$TMP" -czf "$OUT/$NAME.tar.gz" "$NAME"
(cd "$OUT" && sha256sum "$NAME.tar.gz" > SHA256SUMS)
echo "Создан: $OUT/$NAME.tar.gz"
