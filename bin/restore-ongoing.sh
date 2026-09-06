#!/bin/bash
# Reopen every "ongoing" Claude Code session that is not currently running,
# each in its own Terminal.app window and its own working directory.
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

LINES="$(python3 - "$HERE/../lib" <<'PY'
import os, sys
sys.path.insert(0, sys.argv[1])
import cbs

pins = cbs.read_json(cbs.pins_file(), {})
ongoing = set((pins.get("ongoing") or {}).keys())

active = set()
sdir = cbs.sessions_dir()
if sdir.is_dir():
    for f in sdir.glob("*.json"):
        info = cbs.read_json(f, {})
        pid, sid = info.get("pid"), info.get("sessionId")
        if pid and sid:
            try:
                os.kill(pid, 0)
                active.add(sid)
            except Exception:
                pass

cache = cbs.read_json(cbs.cache_file(), {})
sessions = cache.get("sessions") or {}
for sid in sorted(ongoing - active):
    cwd = (sessions.get(sid) or {}).get("cwd") or os.path.expanduser("~")
    print(f"{sid}\t{cwd}")
PY
)"

if [ -z "$LINES" ]; then
    osascript -e 'display notification "All ongoing sessions are already running" with title "Claude Code"'
    exit 0
fi

COUNT=0
while IFS=$'\t' read -r SID CWD; do
    [ -z "$SID" ] && continue
    CMD="cd '$CWD' && claude --resume $SID"
    ESCAPED="$(printf '%s' "$CMD" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    osascript -e "tell application \"Terminal\" to do script \"$ESCAPED\"" >/dev/null
    COUNT=$((COUNT+1))
done <<< "$LINES"

osascript -e "display notification \"Reopened $COUNT ongoing session(s)\" with title \"Claude Code\""
