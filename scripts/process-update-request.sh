#!/usr/bin/env bash
set -Eeuo pipefail
BASE=/opt/vps-bill
REQDIR="$BASE/update-requests"
REQUEST="$REQDIR/request.json"
PROCESSING="$REQDIR/processing.json"
STATUS="$REQDIR/status.json"
DOWNLOADS="$BASE/update-downloads"
REPO="flu-ghsh/vps-bill"
mkdir -p "$REQDIR" "$DOWNLOADS"

[[ -f "$REQUEST" ]] || exit 0
mv "$REQUEST" "$PROCESSING"

read_json(){ python3 - "$PROCESSING" "$1" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
print(obj.get(sys.argv[2],''))
PY
}
REQUEST_ID=$(read_json request_id)
VERSION=$(read_json version)
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Некорректная версия" >&2; exit 1; }

write_status(){
  local state="$1" error="${2:-}"
  python3 - "$STATUS.tmp" "$REQUEST_ID" "$VERSION" "$state" "$error" <<'PY'
import json,sys
from datetime import datetime
path,request_id,version,state,error=sys.argv[1:]
data={"request_id":request_id,"version":version,"state":state,"updated_at":datetime.now().astimezone().isoformat(timespec='seconds')}
if error: data["error"]=error
open(path,'w',encoding='utf-8').write(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
PY
  chmod 644 "$STATUS.tmp"
  mv "$STATUS.tmp" "$STATUS"
}

on_error(){
  local rc=$? line=${BASH_LINENO[0]:-?}
  write_status error "update bridge failed (rc=$rc, line=$line)"
  rm -f "$PROCESSING"
  exit "$rc"
}
trap on_error ERR
write_status running

API="$DOWNLOADS/latest.json"
curl -fsSL -H 'Accept: application/vnd.github+json' -H 'User-Agent: VPS-Bill' \
  "https://api.github.com/repos/$REPO/releases/latest" -o "$API"

readarray -t META < <(python3 - "$API" "$VERSION" <<'PY'
import json,sys
obj=json.load(open(sys.argv[1],encoding='utf-8')); version=sys.argv[2]
tag=str(obj.get('tag_name') or '')
actual=tag[1:] if tag.startswith('v') else tag
if actual != version:
    raise SystemExit(f'Latest GitHub release is {actual}, requested {version}')
name=f'vps-bill-{version}.tar.gz'
asset=None
for a in obj.get('assets') or []:
    if a.get('name') == name:
        asset=a; break
if not asset:
    raise SystemExit(f'Asset {name} not found')
print(asset.get('browser_download_url') or '')
print(asset.get('digest') or '')
checksum=''
for a in obj.get('assets') or []:
    if a.get('name') in {name+'.sha256','SHA256SUMS'}:
        checksum=a.get('browser_download_url') or ''; break
print(checksum)
PY
)
URL="${META[0]:-}"; DIGEST="${META[1]:-}"; CHECKSUM_URL="${META[2]:-}"
[[ "$URL" == https://github.com/flu-ghsh/vps-bill/releases/download/* ]] || { echo "Некорректный URL release asset" >&2; false; }
DEST="$DOWNLOADS/vps-bill-$VERSION.tar.gz"
curl -fL "$URL" -o "$DEST"

EXPECTED=""
if [[ "$DIGEST" == sha256:* ]]; then
  EXPECTED="${DIGEST#sha256:}"
elif [[ -n "$CHECKSUM_URL" ]]; then
  CS="$DOWNLOADS/checksum-$VERSION.txt"
  curl -fsSL "$CHECKSUM_URL" -o "$CS"
  EXPECTED=$(python3 - "$CS" "$(basename "$DEST")" <<'PY'
import re,sys
text=open(sys.argv[1],encoding='utf-8',errors='replace').read(); name=sys.argv[2]
for line in text.splitlines():
    m=re.match(r'^([0-9a-fA-F]{64})\s+\*?(.+)$',line.strip())
    if m and m.group(2).strip()==name:
        print(m.group(1).lower()); break
PY
)
fi
if [[ -n "$EXPECTED" ]]; then
  ACTUAL=$(sha256sum "$DEST" | awk '{print $1}')
  [[ "$ACTUAL" == "$EXPECTED" ]] || { echo "SHA256 не совпал" >&2; false; }
fi

# Штатный updater сам делает backup, тестовую миграцию, health-check и rollback.
/usr/local/bin/vps-bill-update --file "$DEST"
write_status success
rm -f "$PROCESSING"
trap - ERR
