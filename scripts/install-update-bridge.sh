#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите от root" >&2; exit 1; }

BASE=/opt/vps-bill
REQ="$BASE/update-requests"
DL="$BASE/update-downloads"
BOT_UID=10001
BOT_GID=10001

# The bot runs as uid/gid 10001 and must be able to publish request.json.
# Repair permissions on every install/update, including hosts upgraded from
# older releases where update-requests may have been created by root.
install -d -o "$BOT_UID" -g "$BOT_GID" -m 0770 "$REQ"
install -d -o root -g root -m 0755 "$DL"
chown "$BOT_UID:$BOT_GID" "$REQ"
chmod 0770 "$REQ"

# Remove only stale temporary request files. Active request/processing/status
# files are preserved so an update cannot be lost merely by reinstalling the bridge.
find "$REQ" -maxdepth 1 -type f -name '.request.*.tmp' -delete 2>/dev/null || true
rm -f "$REQ/.request.json.tmp" 2>/dev/null || true

# Remove the old unattended auto-update mechanism if it still exists.
systemctl disable --now vps-bill-auto-update.timer >/dev/null 2>&1 || true
systemctl stop vps-bill-auto-update.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/vps-bill-auto-update.timer /etc/systemd/system/vps-bill-auto-update.service

cat >/etc/systemd/system/vps-bill-update-request.service <<'UNIT'
[Unit]
Description=VPS Bill requested update
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/opt/vps-bill/current/scripts/process-update-request.sh
UNIT

cat >/etc/systemd/system/vps-bill-update-request.path <<'UNIT'
[Unit]
Description=Watch VPS Bill update requests

[Path]
PathExists=/opt/vps-bill/update-requests/request.json
Unit=vps-bill-update-request.service

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now vps-bill-update-request.path >/dev/null

# One final cleanup after replacing the units. This makes old fixed-name temp
# files harmless even on hosts that skipped several releases.
rm -f "$REQ/.request.json.tmp" 2>/dev/null || true
find "$REQ" -maxdepth 1 -type f -name '.request.*.tmp' -delete 2>/dev/null || true
chown "$BOT_UID:$BOT_GID" "$REQ"
chmod 0770 "$REQ"

echo "VPS Bill update bridge установлен"
