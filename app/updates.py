from __future__ import annotations

import json
import re
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiohttp

GITHUB_REPO = "flu-ghsh/vps-bill"
GITHUB_LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RAW_CHANGELOG = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{{ref}}/CHANGELOG.md"
_VERSION_RE = re.compile(r"^(?:v\.?|\.)?(\d+)\.(\d+)\.(\d+)$", re.IGNORECASE)


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


def changelog_section(text: str, version: str) -> str:
    """Return only the CHANGELOG.md section for one semantic version."""
    version_tuple(version)
    lines = str(text or "").splitlines()
    start: int | None = None
    header_re = re.compile(rf"^##\s+\[?v?{re.escape(version)}\]?(?:\s|$)", re.IGNORECASE)
    any_header_re = re.compile(r"^##\s+")
    for idx, line in enumerate(lines):
        if start is None:
            if header_re.match(line.strip()):
                start = idx + 1
            continue
        if any_header_re.match(line.strip()):
            break
    if start is None:
        raise ValueError(f"В CHANGELOG.md нет раздела для версии {version}")
    end = len(lines)
    for idx in range(start, len(lines)):
        if any_header_re.match(lines[idx].strip()):
            end = idx
            break
    body = "\n".join(lines[start:end]).strip()
    if not body:
        raise ValueError(f"Раздел CHANGELOG.md для версии {version} пуст")
    return body


async def _fetch_changelog_notes(session: aiohttp.ClientSession, tag: str, version: str) -> str:
    # Prefer the exact release tag so notes always match the installed archive.
    refs = [tag, f"v{version}"]
    seen: set[str] = set()
    last_error = ""
    for ref in refs:
        if not ref or ref in seen:
            continue
        seen.add(ref)
        url = GITHUB_RAW_CHANGELOG.format(ref=ref)
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    last_error = f"CHANGELOG HTTP {response.status}"
                    continue
                return changelog_section(await response.text(), version)
        except Exception as exc:
            last_error = str(exc)
    raise RuntimeError(f"Не удалось получить CHANGELOG.md для {version}: {last_error or 'неизвестная ошибка'}")


def _release_from_payload(payload: dict[str, Any]) -> ReleaseInfo:
    tag = str(payload.get("tag_name") or "").strip()
    match = _VERSION_RE.match(tag)
    if not match:
        raise ValueError(f"Некорректная версия GitHub Release: {tag}")
    version = '.'.join(match.groups())
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
        notes="",
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
            release = _release_from_payload(await response.json())
        notes = await _fetch_changelog_notes(session, release.tag, release.version)
        return ReleaseInfo(
            version=release.version,
            tag=release.tag,
            title=release.title,
            notes=notes,
            html_url=release.html_url,
            asset_url=release.asset_url,
        )



def changelog_to_telegram_html(notes: str, limit: int = 3000) -> str:
    """Render CHANGELOG markdown bullets/inline code as Telegram HTML."""
    import html

    value = str(notes or "").strip()
    if not value:
        return "Изменения не указаны."
    if len(value) > limit:
        value = value[:limit].rstrip() + "…"

    rendered: list[str] = []
    inline_code = re.compile(r"`([^`]+)`")
    for raw in value.splitlines():
        line = raw.rstrip()
        prefix = ""
        if line.lstrip().startswith("- "):
            indent = line[: len(line) - len(line.lstrip())]
            line = line.lstrip()[2:]
            prefix = indent + "• "
        pieces: list[str] = []
        pos = 0
        for match in inline_code.finditer(line):
            pieces.append(html.escape(line[pos:match.start()], quote=False))
            pieces.append(f"<code>{html.escape(match.group(1), quote=False)}</code>")
            pos = match.end()
        pieces.append(html.escape(line[pos:], quote=False))
        rendered.append(prefix + "".join(pieces))
    return "\n".join(rendered).strip()

def cleanup_stale_update_temps(directory: Path) -> None:
    """Remove stale temporary request files left by old updater versions."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    candidates = [directory / ".request.json.tmp"]
    try:
        candidates.extend(directory.glob(".request.*.tmp"))
    except OSError:
        pass
    seen: set[Path] = set()
    for stale in candidates:
        if stale in seen:
            continue
        seen.add(stale)
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            pass


def create_update_request(directory: Path, version: str) -> str:
    version_tuple(version)
    directory.mkdir(parents=True, exist_ok=True)
    request_path = directory / "request.json"
    processing = directory / "processing.json"

    cleanup_stale_update_temps(directory)

    if request_path.exists() or processing.exists():
        raise RuntimeError("Обновление уже запущено")
    request_id = f"{version}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    data = {
        "request_id": request_id,
        "version": version,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    # Use a unique temporary file in the same directory. Older releases used a
    # fixed .request.json.tmp name; if a root-owned stale file was left by a
    # host-side bridge, the non-root bot (uid 10001) could not overwrite it.
    # A unique temp file avoids that collision while os.replace keeps the
    # request publication atomic for the systemd path watcher.
    fd, tmp_name = tempfile.mkstemp(prefix=".request.", suffix=".tmp", dir=directory)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, request_path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return request_id


def read_update_status(directory: Path) -> dict[str, Any] | None:
    path = directory / "status.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
