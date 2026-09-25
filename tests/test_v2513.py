from app.default_emojis import DEFAULT_CUSTOM_EMOJIS
from pathlib import Path


def test_resetall_callback_registration_accepts_page_suffix():
    text = Path("app/handlers.py").read_text()
    assert 'F.data.startswith("emoji:resetall:yes")' in text


def test_new_default_emojis_are_built_in():
    assert DEFAULT_CUSTOM_EMOJIS["cabinet"] == "5884343982816759327"
    assert DEFAULT_CUSTOM_EMOJIS["update"] == "6039802767931871481"
