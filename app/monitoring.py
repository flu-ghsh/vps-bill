from __future__ import annotations

import asyncio
import re


_IP_RE = re.compile(r"[0-9A-Fa-f:.]+")


def valid_ip(value: str) -> bool:
    value = str(value or "").strip()
    return bool(value and len(value) <= 255 and _IP_RE.fullmatch(value))


async def ping_once(ip: str, timeout: int) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-n", "-c", "1", "-W", str(timeout), ip,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await asyncio.wait_for(proc.wait(), timeout=timeout + 2) == 0
    except Exception as exc:
        print(f"ping {ip} failed: {exc}", flush=True)
        return False


async def ping_probe(ip: str, timeout: int, *, attempts: int = 3, delay: float = 2.0) -> bool:
    if not valid_ip(ip):
        return False
    for attempt in range(max(1, attempts)):
        if await ping_once(ip, timeout):
            return True
        if attempt + 1 < attempts:
            await asyncio.sleep(delay)
    return False


async def tcp_probe(ip: str, port: int, timeout: int) -> bool:
    if not valid_ip(ip):
        return False
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, int(port)), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except ConnectionRefusedError:
        # TCP RST means the host/network stack replied. The service may be closed,
        # but for host-availability monitoring this still proves the VPS is reachable.
        return True
    except (asyncio.TimeoutError, OSError) as exc:
        print(f"tcp {ip}:{port} failed: {exc}", flush=True)
        return False


async def probe_host(ip: str, *, method: str, port: int, timeout: int) -> tuple[bool, dict[str, str]]:
    method = method if method in {"auto", "ping", "tcp"} else "auto"
    details = {"method": method, "ping": "skip", "tcp": "skip", "port": str(port)}

    if method in {"auto", "ping"}:
        ping_ok = await ping_probe(ip, timeout)
        details["ping"] = "ok" if ping_ok else "fail"
        if method == "ping" or ping_ok:
            return ping_ok, details

    tcp_ok = await tcp_probe(ip, port, timeout)
    details["tcp"] = "ok" if tcp_ok else "fail"
    return tcp_ok, details
