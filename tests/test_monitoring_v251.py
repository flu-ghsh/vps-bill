import asyncio
from pathlib import Path

from app.db import Database
from app import monitoring


def make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "billing.db")


def test_monitor_defaults_v251(tmp_path):
    db = make_db(tmp_path)
    assert db.monitor_method() == "auto"
    assert db.monitor_tcp_port() == 22


def test_monitor_method_validation(tmp_path):
    db = make_db(tmp_path)
    db.set_setting("monitor_method", "tcp")
    assert db.monitor_method() == "tcp"
    db.set_setting("monitor_method", "wat")
    assert db.monitor_method() == "auto"


def test_monitor_tcp_port_clamped(tmp_path):
    db = make_db(tmp_path)
    db.set_setting("monitor_tcp_port", "443")
    assert db.monitor_tcp_port() == 443
    db.set_setting("monitor_tcp_port", "99999")
    assert db.monitor_tcp_port() == 65535


def test_auto_falls_back_to_tcp(monkeypatch):
    async def fake_ping(ip, timeout, **kwargs):
        return False

    async def fake_tcp(ip, port, timeout):
        assert port == 22
        return True

    monkeypatch.setattr(monitoring, "ping_probe", fake_ping)
    monkeypatch.setattr(monitoring, "tcp_probe", fake_tcp)
    ok, details = asyncio.run(monitoring.probe_host("1.2.3.4", method="auto", port=22, timeout=3))
    assert ok is True
    assert details["ping"] == "fail"
    assert details["tcp"] == "ok"


def test_auto_fails_only_when_ping_and_tcp_fail(monkeypatch):
    async def fake_ping(ip, timeout, **kwargs):
        return False

    async def fake_tcp(ip, port, timeout):
        return False

    monkeypatch.setattr(monitoring, "ping_probe", fake_ping)
    monkeypatch.setattr(monitoring, "tcp_probe", fake_tcp)
    ok, details = asyncio.run(monitoring.probe_host("1.2.3.4", method="auto", port=22, timeout=3))
    assert ok is False
    assert details["ping"] == "fail"
    assert details["tcp"] == "fail"


def test_ping_success_skips_tcp(monkeypatch):
    called = {"tcp": 0}

    async def fake_ping(ip, timeout, **kwargs):
        return True

    async def fake_tcp(ip, port, timeout):
        called["tcp"] += 1
        return False

    monkeypatch.setattr(monitoring, "ping_probe", fake_ping)
    monkeypatch.setattr(monitoring, "tcp_probe", fake_tcp)
    ok, details = asyncio.run(monitoring.probe_host("1.2.3.4", method="auto", port=22, timeout=3))
    assert ok is True
    assert details["ping"] == "ok"
    assert details["tcp"] == "skip"
    assert called["tcp"] == 0
