from pathlib import Path
import re


def test_every_registered_handler_exists():
    text = (Path(__file__).parents[1] / "app" / "handlers.py").read_text()
    registered = set(re.findall(r"register\(self\.([A-Za-z_][A-Za-z0-9_]*)", text))
    methods = set(re.findall(r"^\s+(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M))
    missing = sorted(registered - methods)
    assert not missing, f"Registered handlers missing methods: {missing}"
