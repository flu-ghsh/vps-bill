#!/usr/bin/env bash
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Запустите от root" >&2; exit 1; }
BASE=/opt/vps-bill
REQ="$BASE/update-requests"
DL="$BASE/update-downloads"
mkdir -p "$REQ" "$DL"
chown 10001:10001 "$REQ"
chmod 750 "$REQ"
chmod 755 "$DL"

# Удаляем старый механизм автоматической установки по timer.
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

echo "VPS Bill update bridge установлен"
