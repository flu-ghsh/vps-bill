#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${VPS_BILL_REPO_DIR:-/opt/vps-bill}"
GITHUB_REPO="${VPS_BILL_GITHUB_REPO:-flu-ghsh/vps-bill}"
info(){ printf '\033[1;34m▶\033[0m %s\n' "$*"; }
ok(){ printf '\033[1;32m✔\033[0m %s\n' "$*"; }
fail(){ printf '\033[1;31m✖\033[0m %s\n' "$*" >&2; exit 1; }
TMP_ITEMS=()
cleanup(){ for p in "${TMP_ITEMS[@]:-}"; do [[ -n "$p" ]] && rm -rf -- "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

[[ $# -eq 1 ]] || fail "Использование: $0 X.Y.Z"
VERSION="${1#v}"; VERSION="${VERSION#.}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Некорректная версия: $1"
TAG="v$VERSION"
cd "$REPO_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "$REPO_DIR не git-репозиторий"
BRANCH="$(git branch --show-current)"; [[ -n "$BRANCH" ]] || fail "detached HEAD"

ARCHIVE=""
for candidate in "/opt/vps-bill-${VERSION}.tar.gz" "$REPO_DIR/vps-bill-${VERSION}.tar.gz" "$REPO_DIR/release/vps-bill-${VERSION}.tar.gz"; do
  [[ -f "$candidate" ]] && { ARCHIVE="$candidate"; break; }
done
[[ -n "$ARCHIVE" ]] || fail "Не найден архив vps-bill-${VERSION}.tar.gz"
tar -tzf "$ARCHIVE" >/dev/null || fail "Архив повреждён"

EXTRACT_DIR="$(mktemp -d)"; TMP_ITEMS+=("$EXTRACT_DIR")
tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR"
VERSION_FILE="$(find "$EXTRACT_DIR" -type f -name VERSION -print -quit)"
[[ -n "$VERSION_FILE" ]] || fail "В архиве нет VERSION"
ARCHIVE_ROOT="$(dirname "$VERSION_FILE")"
[[ "$(tr -d '[:space:]' < "$VERSION_FILE")" == "$VERSION" ]] || fail "VERSION в архиве не совпадает"

# Runtime/secret paths вообще не участвуют в синхронизации.
for bad in data backups update-requests update-downloads .env; do
  if tar -tzf "$ARCHIVE" | grep -Eq "(^|/)${bad}(/|$)"; then
    fail "В release archive попал runtime/secret: $bad"
  fi
done

info "Синхронизирую ветку с GitHub..."
git fetch origin "$BRANCH"
git rebase --autostash "origin/$BRANCH"

sync_dir(){
  local name="$1"
  [[ -d "$ARCHIVE_ROOT/$name" ]] || return 0
  mkdir -p "$REPO_DIR/$name"
  rsync -a --delete --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='*.pyc' "$ARCHIVE_ROOT/$name/" "$REPO_DIR/$name/"
}
sync_file(){
  local name="$1"
  [[ -f "$ARCHIVE_ROOT/$name" ]] && cp -aL "$ARCHIVE_ROOT/$name" "$REPO_DIR/$name"
}

for d in app scripts tests systemd docs; do sync_dir "$d"; done
for f in Dockerfile requirements.txt .dockerignore .env.example compose.example.yaml install.sh update.sh CHANGELOG.md VERSION; do sync_file "$f"; done
# README.md намеренно не перезаписываем: он пользовательский.
# compose.yaml, .env и runtime-каталоги намеренно не трогаем.

NOTES_FILE="$(mktemp)"; TMP_ITEMS+=("$NOTES_FILE")
python3 - "$REPO_DIR/CHANGELOG.md" "$VERSION" "$NOTES_FILE" <<'PYNOTES'
from pathlib import Path
import re,sys
s=Path(sys.argv[1]).read_text(encoding='utf-8'); v=re.escape(sys.argv[2]); out=Path(sys.argv[3])
m=re.search(rf'(?ms)^##\s+\[?v?{v}\]?(?:\s+.*?)?\n(.*?)(?=^##\s+|\Z)', s)
if not m or not m.group(1).strip(): raise SystemExit('CHANGELOG section missing/empty')
out.write_text(m.group(1).strip()+"\n", encoding='utf-8')
PYNOTES

if [[ -n "$(git status --porcelain)" ]]; then
  ADD_PATHS=()
  for p in app scripts tests systemd docs Dockerfile requirements.txt .dockerignore .env.example compose.example.yaml install.sh update.sh README.md CHANGELOG.md VERSION; do
    [[ -e "$REPO_DIR/$p" ]] && ADD_PATHS+=("$p")
  done
  git add -A -- "${ADD_PATHS[@]}"
  if git diff --cached --name-only | grep -E '^(\.env$|compose\.yaml$|data/|backups/|update-requests/|update-downloads/)' >/dev/null; then
    git reset -- .env compose.yaml data backups update-requests update-downloads 2>/dev/null || true
    fail "В staging попали runtime/secrets"
  fi
  git commit -m "Release $TAG"
fi

git push origin "$BRANCH"
HEAD_SHA="$(git rev-parse HEAD)"
if ! git rev-parse "$TAG" >/dev/null 2>&1; then git tag -a "$TAG" -m "VPS Bill $TAG"; fi
[[ "$(git rev-list -n1 "$TAG")" == "$HEAD_SHA" ]] || fail "Tag $TAG указывает на другой commit"
git push origin "$TAG"

CHECKSUM="/tmp/vps-bill-${VERSION}.tar.gz.sha256"
(cd "$(dirname "$ARCHIVE")" && sha256sum "$(basename "$ARCHIVE")") > "$CHECKSUM"
if gh release view "$TAG" --repo "$GITHUB_REPO" >/dev/null 2>&1; then
  gh release upload "$TAG" "$ARCHIVE" "$CHECKSUM" --repo "$GITHUB_REPO" --clobber
else
  gh release create "$TAG" "$ARCHIVE" "$CHECKSUM" --repo "$GITHUB_REPO" --title "VPS Bill $TAG" --notes-file "$NOTES_FILE"
fi
ok "Готово: VPS Bill $TAG опубликован"
