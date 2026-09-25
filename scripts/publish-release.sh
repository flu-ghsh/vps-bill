#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="${VPS_BILL_REPO_DIR:-/opt/vps-bill}"
GITHUB_REPO="${VPS_BILL_GITHUB_REPO:-flu-ghsh/vps-bill}"

info() { printf '\033[1;34m▶\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✔\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m✖\033[0m %s\n' "$*" >&2; exit 1; }

TMP_ITEMS=()
cleanup() {
  local p
  for p in "${TMP_ITEMS[@]:-}"; do
    [[ -n "$p" ]] && rm -rf -- "$p" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

[[ $# -eq 1 ]] || fail "Использование: $0 2.5.23"

VERSION="${1#v}"
VERSION="${VERSION#.}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Некорректная версия: $1"
TAG="v${VERSION}"

[[ -d "$REPO_DIR" ]] || fail "Каталог проекта не найден: $REPO_DIR"
cd "$REPO_DIR"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "$REPO_DIR не является git-репозиторием"

BRANCH="$(git branch --show-current)"
[[ -n "$BRANCH" ]] || fail "Git находится в detached HEAD"

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "https://github.com/${GITHUB_REPO}.git"
fi

info "Репозиторий : $GITHUB_REPO"
info "Версия      : $VERSION"
info "Ветка       : $BRANCH"

# 1. Locate release archive.
ARCHIVE=""
for candidate in \
  "/opt/vps-bill-${VERSION}.tar.gz" \
  "$REPO_DIR/vps-bill-${VERSION}.tar.gz" \
  "$REPO_DIR/release/vps-bill-${VERSION}.tar.gz" \
  "$REPO_DIR/current/release/vps-bill-${VERSION}.tar.gz"
do
  if [[ -f "$candidate" ]]; then
    ARCHIVE="$candidate"
    break
  fi
done

[[ -n "$ARCHIVE" ]] || fail "Не найден архив vps-bill-${VERSION}.tar.gz"
tar -tzf "$ARCHIVE" >/dev/null 2>&1 || fail "Архив повреждён: $ARCHIVE"
info "Архив       : $ARCHIVE"

# 2. Extract release archive.
EXTRACT_DIR="$(mktemp -d)"
TMP_ITEMS+=("$EXTRACT_DIR")
tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR"

VERSION_FILE="$(find "$EXTRACT_DIR" -type f -name VERSION -print -quit)"
[[ -n "$VERSION_FILE" ]] || fail "В архиве нет VERSION"

ARCHIVE_ROOT="$(dirname "$VERSION_FILE")"
ARCHIVE_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
[[ "$ARCHIVE_VERSION" == "$VERSION" ]] \
  || fail "В архиве VERSION='$ARCHIVE_VERSION', а публикуется '$VERSION'"

[[ -f "$ARCHIVE_ROOT/CHANGELOG.md" ]] || fail "В архиве нет CHANGELOG.md"

# 3. Sync git branch before touching working tree.
info "Синхронизирую ветку с GitHub..."
git fetch origin "$BRANCH"

LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse "origin/$BRANCH")"
BASE_HEAD="$(git merge-base HEAD "origin/$BRANCH")"

if [[ "$LOCAL_HEAD" == "$REMOTE_HEAD" ]]; then
  ok "Ветка синхронизирована"
elif [[ "$LOCAL_HEAD" == "$BASE_HEAD" ]]; then
  git rebase --autostash "origin/$BRANCH"
  ok "Получены изменения из GitHub"
elif [[ "$REMOTE_HEAD" == "$BASE_HEAD" ]]; then
  ok "Локальная ветка содержит неопубликованные коммиты"
else
  fail "Локальная и удалённая ветки разошлись. Разреши расхождение вручную."
fi

# 4. Sync ALL release source into git working tree.
info "Синхронизирую исходники из release-архива в git..."

sync_dir() {
  local name="$1"
  if [[ -d "$ARCHIVE_ROOT/$name" ]]; then
    mkdir -p "$REPO_DIR/$name"
    rsync -a --delete \
      --exclude='__pycache__/' \
      --exclude='.pytest_cache/' \
      --exclude='*.pyc' \
      "$ARCHIVE_ROOT/$name/" "$REPO_DIR/$name/"
  fi
}

sync_file() {
  local name="$1"
  if [[ -f "$ARCHIVE_ROOT/$name" ]]; then
    cp -a "$ARCHIVE_ROOT/$name" "$REPO_DIR/$name"
  fi
}

sync_dir app
sync_dir scripts
sync_dir tests

for f in \
  Dockerfile \
  requirements.txt \
  .dockerignore \
  .env.example \
  compose.yaml \
  compose.example.yaml \
  install.sh \
  update.sh \
  README.md \
  CHANGELOG.md \
  VERSION
do
  sync_file "$f"
done

# Never copy runtime/secrets from archive even if a broken archive contains them.
rm -rf \
  "$REPO_DIR/data" \
  "$REPO_DIR/backups" \
  "$REPO_DIR/update-requests" \
  2>/dev/null || true

# Never touch real .env.
git checkout -- .env 2>/dev/null || true

ok "Исходники синхронизированы из release-архива"

# 5. Validate changelog section and prepare release notes.
NOTES_FILE="$(mktemp)"
TMP_ITEMS+=("$NOTES_FILE")

set +e
python3 - "$REPO_DIR/CHANGELOG.md" "$VERSION" "$NOTES_FILE" <<'PY'
from pathlib import Path
import re, sys

path = Path(sys.argv[1])
version = sys.argv[2]
out = Path(sys.argv[3])

text = path.read_text(encoding="utf-8")
header = re.compile(
    rf"^##\s+\[?v?{re.escape(version)}\]?(?:\s+.*)?$",
    re.MULTILINE,
)
m = header.search(text)
if not m:
    raise SystemExit(2)

start = m.end()
n = re.search(r"^##\s+", text[start:], re.MULTILINE)
end = start + n.start() if n else len(text)
body = text[start:end].strip()
if not body:
    raise SystemExit(3)

out.write_text(body + "\n", encoding="utf-8")
PY
RC=$?
set -e

case "$RC" in
  0) ;;
  2) fail "В CHANGELOG.md нет секции для версии ${VERSION}" ;;
  3) fail "Секция ${VERSION} в CHANGELOG.md пустая" ;;
  *) fail "Не удалось прочитать CHANGELOG.md" ;;
esac

ok "Release notes для ${VERSION} найдены"

# 6. Ensure version consistency after sync.
[[ "$(tr -d '[:space:]' < "$REPO_DIR/VERSION")" == "$VERSION" ]] \
  || fail "VERSION в git-дереве не совпадает с ${VERSION}"

if [[ -f "$REPO_DIR/app/__init__.py" ]]; then
  SOURCE_VERSION="$(
    python3 - <<'PY'
import re
from pathlib import Path
s = Path("app/__init__.py").read_text(encoding="utf-8")
m = re.search(r'(?m)^__version__\s*=\s*["\']([^"\']+)["\']', s)
print(m.group(1) if m else "")
PY
  )"
  [[ "$SOURCE_VERSION" == "$VERSION" ]] \
    || fail "app/__init__.py содержит '$SOURCE_VERSION' вместо '$VERSION'"
fi

# 7. Check source tree really contains same app as release archive.
if ! diff -qr \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='*.pyc' \
  "$ARCHIVE_ROOT/app" "$REPO_DIR/app" >/tmp/vps-bill-release-diff.$$ 2>&1
then
  cat /tmp/vps-bill-release-diff.$$ >&2
  rm -f /tmp/vps-bill-release-diff.$$
  fail "app/ в git отличается от app/ в release-архиве"
fi
rm -f /tmp/vps-bill-release-diff.$$
ok "Git source совпадает с release source"

# 8. GitHub CLI.
if ! command -v gh >/dev/null 2>&1; then
  warn "GitHub CLI не установлен. Устанавливаю..."
  apt-get update
  apt-get install -y gh
fi

if ! gh auth status >/dev/null 2>&1; then
  warn "GitHub CLI не авторизован"
  gh auth login
fi

# 9. Commit source synced from archive.
if [[ -n "$(git status --porcelain)" ]]; then
  info "Изменения для релиза:"
  git status --short
  info "Создаю commit Release ${TAG}..."
  git add -A
  git commit -m "Release ${TAG}"
else
  ok "Незакоммиченных изменений нет"
fi

# 10. Make sure remote has not changed before push.
info "Проверяю GitHub перед push..."
git fetch origin "$BRANCH"

REMOTE_NOW="$(git rev-parse "origin/$BRANCH")"
BASE_NOW="$(git merge-base HEAD "origin/$BRANCH")"
[[ "$REMOTE_NOW" == "$BASE_NOW" ]] \
  || fail "В GitHub появились новые коммиты. Запусти команду ещё раз."

info "Отправляю ветку ${BRANCH} в GitHub..."
git push origin "$BRANCH"

# 11. Tag.
HEAD_SHA="$(git rev-parse HEAD)"

if git rev-parse "$TAG" >/dev/null 2>&1; then
  TAG_SHA="$(git rev-list -n1 "$TAG")"
  [[ "$TAG_SHA" == "$HEAD_SHA" ]] \
    || fail "Локальный tag $TAG уже существует на другом commit"
else
  git tag -a "$TAG" -m "VPS Bill ${TAG}"
fi

if git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then
  REMOTE_TAG_SHA="$(git ls-remote --tags origin "refs/tags/$TAG^{}" | awk '{print $1}')"
  [[ -n "$REMOTE_TAG_SHA" ]] || \
    REMOTE_TAG_SHA="$(git ls-remote --tags origin "refs/tags/$TAG" | awk '{print $1}')"

  [[ "$REMOTE_TAG_SHA" == "$HEAD_SHA" ]] \
    || fail "Удалённый tag $TAG уже существует на другом commit"

  ok "Удалённый tag $TAG уже существует"
else
  info "Отправляю tag $TAG..."
  git push origin "$TAG"
fi

# 12. SHA256.
CHECKSUM="/tmp/vps-bill-${VERSION}.tar.gz.sha256"
(
  cd "$(dirname "$ARCHIVE")"
  sha256sum "$(basename "$ARCHIVE")"
) > "$CHECKSUM"

SHA256="$(awk '{print $1}' "$CHECKSUM")"
ok "SHA256: $SHA256"

# 13. GitHub Release strictly from CHANGELOG.
if gh release view "$TAG" --repo "$GITHUB_REPO" >/dev/null 2>&1; then
  warn "GitHub Release $TAG уже существует. Обновляю notes и assets..."
  gh release upload "$TAG" "$ARCHIVE" "$CHECKSUM" \
    --repo "$GITHUB_REPO" --clobber
  gh release edit "$TAG" \
    --repo "$GITHUB_REPO" \
    --title "VPS Bill ${TAG}" \
    --notes-file "$NOTES_FILE"
else
  info "Создаю GitHub Release $TAG..."
  gh release create "$TAG" "$ARCHIVE" "$CHECKSUM" \
    --repo "$GITHUB_REPO" \
    --title "VPS Bill ${TAG}" \
    --notes-file "$NOTES_FILE"
fi

ok "Готово: VPS Bill ${TAG} опубликован"
printf '\nhttps://github.com/%s/releases/tag/%s\n' "$GITHUB_REPO" "$TAG"
