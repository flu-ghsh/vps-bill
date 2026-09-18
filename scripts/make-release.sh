#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd); VER=$(tr -d '[:space:]' < "$ROOT/VERSION")
OUT="$ROOT/release"; TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
NAME="vps-bill-$VER"; mkdir -p "$TMP/$NAME"
for x in app scripts tests Dockerfile requirements.txt VERSION compose.yaml install.sh README.md .dockerignore .env.example; do cp -a "$ROOT/$x" "$TMP/$NAME/"; done
mkdir -p "$OUT"; tar -C "$TMP" -czf "$OUT/$NAME.tar.gz" "$NAME"
sha256sum "$OUT/$NAME.tar.gz" > "$OUT/SHA256SUMS"
echo "Создан: $OUT/$NAME.tar.gz"
