from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

GITHUB_REPO = "flu-ghsh/vps-bill"
GITHUB_LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    title: str
    notes: str
    html_url: str
    asset_url: str


def version_tuple(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"Некорректная версия: {value}")
    return tuple(int(x) for x in match.groups())


def is_newer(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def _release_from_payload(payload: dict[str, Any]) -> ReleaseInfo:
    tag = str(payload.get("tag_name") or "").strip()
    version = tag[1:] if tag.startswith("v") else tag
    version_tuple(version)
    wanted = f"vps-bill-{version}.tar.gz"
    asset_url = ""
    for asset in payload.get("assets") or []:
        if str(asset.get("name") or "") == wanted:
            asset_url = str(asset.get("browser_download_url") or "")
            break
    return ReleaseInfo(
        version=version,
        tag=tag or f"v{version}",
        title=str(payload.get("name") or tag or f"VPS Bill {version}"),
        notes=str(payload.get("body") or "").strip(),
        html_url=str(payload.get("html_url") or ""),
        asset_url=asset_url,
    )


async def latest_release(timeout: int = 12) -> ReleaseInfo:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "VPS-Bill",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=client_timeout, headers=headers, trust_env=False) as session:
        async with session.get(GITHUB_LATEST_API) as response:
            if response.status != 200:
                body = (await response.text())[:300]
                raise RuntimeError(f"GitHub API {response.status}: {body}")
            return _release_from_payload(await response.json())


def create_update_request(directory: Path, version: str) -> str:
    version_tuple(version)
    directory.mkdir(parents=True, exist_ok=True)
    request_path = directory / "request.json"
    processing = directory / "processing.json"
    if request_path.exists() or processing.exists():
        raise RuntimeError("Обновление уже запущено")
    request_id = f"{version}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    data = {
        "request_id": request_id,
        "version": version,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    tmp = directory / ".request.json.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(request_path)
    return request_id


def read_update_status(directory: Path) -> dict[str, Any] | None:
    path = directory / "status.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
