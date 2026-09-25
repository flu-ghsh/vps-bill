from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def text(p): return (ROOT / p).read_text(encoding="utf-8")

def test_publish_does_not_delete_runtime():
    s=text("scripts/publish-release.sh")
    assert '"$REPO_DIR/data"' not in s
    assert 'compose.yaml \\' not in s

def test_update_is_not_delete_first():
    s=text("scripts/update.sh")
    assert 'rm -f "$BASE/data/billing.db"' not in s
    assert 'mv -f -- "$RESTORE_TMP" "$DB"' in s
    assert '/opt/vps-bill-safety' in s

def test_restore_is_not_delete_first():
    s=text("scripts/restore.sh")
    assert 'rm -f "$BASE/data/billing.db"' not in s
    assert 'mv -f -- "$RESTORE_TMP" "$DB"' in s

def test_missing_db_guard():
    assert '.initialized' in text("app/main.py")
    assert 'Автоматическое создание новой базы заблокировано' in text("install.sh")
