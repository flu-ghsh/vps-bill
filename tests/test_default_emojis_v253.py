from pathlib import Path

from app.db import Database
from app.default_emojis import DEFAULT_CUSTOM_EMOJIS


def test_builtin_emoji_defaults_are_loaded(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    emojis = db.get_emojis()
    assert emojis["brand"] == "5994750571041525522"
    assert emojis["server"] == "6019462434178211398"
    assert emojis["monitor"] == "5924681813149618024"
    assert "purpose" not in DEFAULT_CUSTOM_EMOJIS


def test_db_override_wins_and_reset_returns_default(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    original = DEFAULT_CUSTOM_EMOJIS["server"]
    db.set_emoji("server", "123456789")
    assert db.get_emojis()["server"] == "123456789"

    # Empty DB override means "use project default".
    db.set_emoji("server", "")
    assert db.get_emojis()["server"] == original


def test_reset_all_returns_project_defaults(tmp_path: Path):
    db = Database(tmp_path / "billing.db")
    db.set_emoji("server", "123456789")
    db.set_emoji("brand", "987654321")
    db.clear_all_emojis()
    emojis = db.get_emojis()
    assert emojis["server"] == DEFAULT_CUSTOM_EMOJIS["server"]
    assert emojis["brand"] == DEFAULT_CUSTOM_EMOJIS["brand"]
