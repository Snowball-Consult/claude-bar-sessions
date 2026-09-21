#!/bin/bash
# Resume a Claude Code session in a new terminal window.
#
# Which terminal app is used comes from the "terminal" key in config.json
# ("Terminal" by default, "Ghostty" also supported). See lib/open-window.sh.
#
# Usage:
#   resume-session.sh <session-id>   resume that session in its own working directory
#   resume-session.sh                open the interactive `claude --resume` picker
#
# SwiftBar splits param2= on spaces, so this script takes only the session ID
# and looks the working directory up in the plugin cache itself.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CBS="$HERE/../lib/cbs.py"
SID="$1"

if [ -n "$SID" ]; then
    CWD="$(python3 "$CBS" session_cwd "$SID")"
    [ -z "$CWD" ] && CWD="$HOME"
    INNER="claude --resume $SID"
else
    CWD="$(python3 "$CBS" last_cwd)"
    [ -z "$CWD" ] && CWD="$HOME"
    INNER="claude --resume"
fi

. "$HERE/../lib/open-window.sh"
TERM_APP="$(python3 "$CBS" terminal)"
cbs_open_window "$CWD" "$INNER" "$TERM_APP" yes
