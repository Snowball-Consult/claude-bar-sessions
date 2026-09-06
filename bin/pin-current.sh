#!/bin/bash
# Pin (or toggle) the Claude Code session this script is running inside.
# Usage (from a shell started by Claude Code, for example a skill):
#   pin-current.sh           # toggle
#   pin-current.sh pin       # force pin
#   pin-current.sh unpin     # force unpin
#   pin-current.sh status    # print "pinned" or "not pinned", change nothing
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CBS="$HERE/../lib/cbs.py"
ACTION="${1:-toggle}"

# Walk up from our parent: skill invocations add shell layers between this
# script and the Claude Code process, so $PPID alone is not always enough.
SID="$(python3 "$CBS" current_session_id "$PPID")"
if [ -z "$SID" ]; then
    echo "error: could not resolve the current Claude Code session ID" >&2
    echo "  walked up from PPID=$PPID; no matching file in $(python3 "$CBS" claude_home)/sessions" >&2
    exit 1
fi

if [ "$ACTION" = "status" ]; then
    python3 - "$HERE/../lib" "$SID" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
import cbs
data = cbs.read_json(cbs.pins_file(), {})
print(("pinned" if sys.argv[2] in (data.get("ongoing") or {}) else "not pinned"), sys.argv[2])
PY
    exit 0
fi

exec "$HERE/pin-session.sh" "$SID" "$ACTION"
