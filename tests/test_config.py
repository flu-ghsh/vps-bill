from pathlib import Path

from app.config import Settings


def test_settings_accept_double_quoted_dotenv_values(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BOT_TOKEN", '"123456:ABCDEF"')
    monkeypatch.setenv("ADMIN_IDS", '"222994533,333444555"')
    monkeypatch.setenv("TELEGRAM_PROXY", '"socks5://s5.example.com:1080"')
    monkeypatch.setenv("TZ", '"Europe/Moscow"')
    monkeypatch.setenv("CHECK_INTERVAL_SECONDS", '"60"')
    monkeypatch.setenv("DB_PATH", f'"{tmp_path / "billing.db"}"')
    monkeypatch.setenv("BACKUPS_DIR", f'"{tmp_path / "backups"}"')
    monkeypatch.setenv("UPDATE_MANIFEST_URL", '"https://example.com/latest.json"')

    s = Settings.from_env()
    assert s.bot_token == "123456:ABCDEF"
    assert s.admin_ids == frozenset({222994533, 333444555})
    assert s.telegram_proxy == "socks5://s5.example.com:1080"
    assert s.timezone == "Europe/Moscow"
    assert s.check_interval == 60
    assert s.db_path == tmp_path / "billing.db"
    assert s.backups_dir == tmp_path / "backups"
    assert s.update_manifest_url == "https://example.com/latest.json"


def test_settings_accept_unquoted_values(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123456:ABCDEF")
    monkeypatch.setenv("ADMIN_IDS", "222994533")
    monkeypatch.setenv("TELEGRAM_PROXY", "s5.example.com:1080")
    s = Settings.from_env()
    assert s.admin_ids == frozenset({222994533})
    assert s.telegram_proxy == "socks5://s5.example.com:1080"
