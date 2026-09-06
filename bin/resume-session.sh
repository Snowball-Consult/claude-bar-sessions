#!/bin/bash
# Resume a Claude Code session in a new Terminal.app window.
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
    CMD="cd '$CWD' && claude --resume $SID"
else
    CWD="$(python3 "$CBS" last_cwd)"
    [ -z "$CWD" ] && CWD="$HOME"
    CMD="cd '$CWD' && claude --resume"
fi

# Escape for an AppleScript string literal.
ESCAPED="$(printf '%s' "$CMD" | sed 's/\\/\\\\/g; s/"/\\"/g')"
osascript -e "tell application \"Terminal\" to do script \"$ESCAPED\"" \
          -e 'tell application "Terminal" to activate' >/dev/null
