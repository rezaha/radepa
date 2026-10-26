#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
target=/opt/radepa
python="$target/venv/bin/python"
[[ $EUID -eq 0 ]] || { echo "Run as root."; exit 1; }
[[ -x "$python" && -f "$target/.env" && -f "$target/data/bot.db" ]] || { echo "Existing installation not found"; exit 1; }
[[ $(systemctl show radepa.service -p WorkingDirectory --value) == "$target" ]] || { echo "Unexpected service directory"; exit 1; }
"$python" - "$source_dir" "$target" <<'PYMAN'
import hashlib,json,sys
from pathlib import Path
source,target=map(Path,sys.argv[1:])
manifest=json.loads((source/'channel-update-manifest.json').read_text())
for name,h in manifest.items():
    candidate=target/name
    current=hashlib.sha256(candidate.read_bytes()).hexdigest() if candidate.exists() else None
    if current not in (h['before'],h['after']):
        raise SystemExit(f"Server file differs: {name}. Nothing changed.")
    if hashlib.sha256((source/name).read_bytes()).hexdigest()!=h['after']:
        raise SystemExit(f"Package file differs: {name}")
PYMAN
cd "$source_dir"
"$python" - <<'PYTEST'
from dotenv import load_dotenv
load_dotenv('/opt/radepa/.env',override=True)
import app.main
print('Preflight import OK')
PYTEST
mkdir -p /root/radepa-backups
chmod 700 /root/radepa-backups
backup=$(mktemp -d /root/radepa-backups/channel-update-XXXXXXXX)
cp -a "$target/app" "$backup/app"
cp -p "$target/.env" "$backup/.env"
chmod 600 "$backup/.env"
echo "Backup: $backup"
was_active=$(systemctl is-active radepa.service || true)
service_stopped=0
rollback() {
 status=$?; trap - ERR
 if [[ $service_stopped == 1 ]]; then
   systemctl stop radepa.service || true
   cp -a "$backup/app/." "$target/app/"
   if [[ ! -f "$backup/app/handlers/channel_stats.py" ]]; then rm -f "$target/app/handlers/channel_stats.py"; fi
   if [[ $was_active == active ]]; then systemctl start radepa.service || true; fi
   echo "Rollback performed; backup: $backup" >&2
 fi
 exit "$status"
}
trap rollback ERR
systemctl stop radepa.service
service_stopped=1
"$python" - "$backup" "$source_dir" "$target" <<'PYCOPY'
import json,shutil,sqlite3,sys
from pathlib import Path
backup,source,target=map(Path,sys.argv[1:])
with sqlite3.connect(target/'data/bot.db') as src:
    with sqlite3.connect(backup/'bot.db') as dst: src.backup(dst)
for name in json.loads((source/'channel-update-manifest.json').read_text()):
    dest=target/name
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source/name,dest)
PYCOPY
cd "$target"
"$python" -m compileall -q app
"$python" - <<'PYIMPORT'
import app.main
PYIMPORT
systemctl start radepa.service
sleep 5
systemctl is-active --quiet radepa.service
trap - ERR
echo 'CHANNEL_UPDATE_OK: test /start, /channel and /channelstats (admin).'
