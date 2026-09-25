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


async def tcp_probe_detailed(ip: str, port: int, timeout: int) -> tuple[bool, str]:
    """Return (host_reachable, tcp_status).

    tcp_status values:
      ok       - TCP connection established;
      refused  - target returned TCP RST (host reachable, service/port closed);
      timeout  - no TCP reply before timeout;
      error    - another socket/network error;
      invalid  - invalid target address.

    A refused connection still proves that the VPS/network stack is reachable,
    which is what Auto mode uses as the ICMP fallback.
    """
    if not valid_ip(ip):
        return False, "invalid"
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, int(port)), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True, "ok"
    except ConnectionRefusedError:
        return True, "refused"
    except asyncio.TimeoutError as exc:
        print(f"tcp {ip}:{port} timeout: {exc}", flush=True)
        return False, "timeout"
    except OSError as exc:
        print(f"tcp {ip}:{port} failed: {exc}", flush=True)
        return False, "error"


async def tcp_probe(ip: str, port: int, timeout: int) -> bool:
    ok, _status = await tcp_probe_detailed(ip, port, timeout)
    return ok


async def probe_host(ip: str, *, method: str, port: int, timeout: int) -> tuple[bool, dict[str, str]]:
    method = method if method in {"auto", "ping", "tcp"} else "auto"
    details = {"method": method, "ping": "skip", "tcp": "skip", "port": str(port)}

    if method in {"auto", "ping"}:
        ping_ok = await ping_probe(ip, timeout)
        details["ping"] = "ok" if ping_ok else "fail"
        if method == "ping" or ping_ok:
            # In Auto mode TCP is intentionally not executed after a successful Ping.
            # Keep the explicit 'skip' state so notifications don't claim the port failed.
            return ping_ok, details

    tcp_ok, tcp_status = await tcp_probe_detailed(ip, port, timeout)
    details["tcp"] = tcp_status
    return tcp_ok, details
