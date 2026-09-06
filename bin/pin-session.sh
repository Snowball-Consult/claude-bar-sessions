#!/bin/bash
# Toggle the "ongoing" pin for a Claude Code session.
# Usage: pin-session.sh <session-id> [pin|unpin|toggle]   (default: toggle)
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SID="$1"
ACTION="${2:-toggle}"

if [ -z "$SID" ]; then
    echo "usage: pin-session.sh <session-id> [pin|unpin|toggle]" >&2
    exit 1
fi

python3 - "$HERE/../lib" "$SID" "$ACTION" <<'PY'
import sys
from datetime import datetime, timezone

sys.path.insert(0, sys.argv[1])
import cbs

sid, action = sys.argv[2], sys.argv[3]
data = cbs.read_json(cbs.pins_file(), {})
if not isinstance(data, dict) or data.get("version") != 1:
    data = {"version": 1, "ongoing": {}}
ongoing = data.setdefault("ongoing", {})
is_pinned = sid in ongoing

if action == "pin" or (action == "toggle" and not is_pinned):
    ongoing[sid] = {"pinnedAt": datetime.now(timezone.utc).isoformat()}
    result = "pinned"
elif action == "unpin" or (action == "toggle" and is_pinned):
    ongoing.pop(sid, None)
    result = "unpinned"
else:
    result = "noop"

cbs.write_json_atomic(cbs.pins_file(), data)
print(f"{result} {sid}")
PY
