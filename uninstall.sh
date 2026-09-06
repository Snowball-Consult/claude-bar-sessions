#!/bin/bash
# Remove claude-bar-sessions from SwiftBar and Claude Code settings.
# Leaves SwiftBar itself and the state folder in place (path printed at the end).
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CURRENT_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
if [ -n "$CURRENT_DIR" ] && [ -L "$CURRENT_DIR/claude-bar-sessions.5m.py" ]; then
  rm "$CURRENT_DIR/claude-bar-sessions.5m.py"
  echo "removed plugin symlink from $CURRENT_DIR"
fi
if [ "$CURRENT_DIR" = "$REPO/plugin" ]; then
  defaults delete com.ameba.SwiftBar PluginDirectory
  echo "SwiftBar plugin folder unset (it pointed at this repo)"
fi

SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
  python3 - "$SETTINGS" "$REPO/hooks/auto-name-session.py" <<'PY'
import json, sys
path, marker = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
groups = data.get("hooks", {}).get("UserPromptSubmit", [])
kept, removed = [], 0
for g in groups:
    hooks = [h for h in g.get("hooks", []) if marker not in (h.get("command") or "")]
    removed += len(g.get("hooks", [])) - len(hooks)
    if hooks:
        g["hooks"] = hooks
        kept.append(g)
if removed:
    data["hooks"]["UserPromptSubmit"] = kept
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"removed {removed} hook entr{'y' if removed == 1 else 'ies'} from {path}")
PY
fi

osascript -e 'tell application "System Events" to delete (every login item whose name is "SwiftBar")' >/dev/null 2>&1 || true
pkill -x SwiftBar 2>/dev/null && open -a SwiftBar || true
echo "state folder kept: $(python3 "$REPO/lib/cbs.py" state_dir)"
