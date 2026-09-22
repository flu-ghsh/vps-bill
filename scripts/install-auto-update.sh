#!/usr/bin/env bash
# Совместимость с updater из 2.5.7/2.5.8: вместо старого timer ставим ручной update bridge.
exec /opt/vps-bill/current/scripts/install-update-bridge.sh "$@"
