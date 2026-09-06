#!/bin/bash
# Install claude-bar-sessions: SwiftBar plugin + helpers, optional naming hook.
#
# Usage: ./install.sh [options]
#   --plugin-dir DIR   Use DIR as the SwiftBar plugin folder (symlinks the plugin
#                      into it). Default: reuse SwiftBar's configured folder if it
#                      has one, otherwise point SwiftBar at this repo's plugin/.
#   --hook             Wire the session-naming hook into ~/.claude/settings.json
#   --no-login-item    Do not add SwiftBar to Login Items
#   --no-launch        Do not (re)start SwiftBar at the end
#   --dry-run          Print what would happen
#
# Safe to run again: every step checks its own state first.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_SRC="$REPO/plugin/claude-bar-sessions.5m.py"
PLUGIN_DIR=""
WITH_HOOK=0
LOGIN_ITEM=1
LAUNCH=1
DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --plugin-dir) PLUGIN_DIR="$2"; shift 2 ;;
    --hook) WITH_HOOK=1; shift ;;
    --no-login-item) LOGIN_ITEM=0; shift ;;
    --no-launch) LAUNCH=0; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say()  { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else eval "$@"; fi; }

[ "$(uname -s)" = "Darwin" ] || { echo "SwiftBar is macOS only." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required (xcode-select --install)." >&2; exit 1; }

# ---------------------------------------------------------------------------
step "SwiftBar"
find_swiftbar() {
  local c
  for c in /Applications/SwiftBar.app "$HOME/Applications/SwiftBar.app" /Applications/Setapp/SwiftBar.app; do
    [ -d "$c" ] && { echo "$c"; return; }
  done
  mdfind "kMDItemCFBundleIdentifier == 'com.ameba.SwiftBar'" 2>/dev/null | head -1
}
SWIFTBAR_APP="$(find_swiftbar)"
if [ -n "$SWIFTBAR_APP" ]; then
  say "already installed at $SWIFTBAR_APP"
elif command -v brew >/dev/null; then
  # Older Homebrew accepts --no-quarantine; Homebrew 5 dropped the flag. Either
  # way, strip the quarantine attribute afterwards: a quarantined SwiftBar can
  # hang on first launch when opened from a script (Gatekeeper's dialog never
  # gets answered).
  run "brew install --cask --no-quarantine swiftbar 2>/dev/null || brew install --cask swiftbar"
  SWIFTBAR_APP="/Applications/SwiftBar.app"
  run "xattr -dr com.apple.quarantine '$SWIFTBAR_APP' 2>/dev/null || true"
  run "defaults write com.ameba.SwiftBar SUEnableAutomaticChecks -bool false"
else
  echo "Install SwiftBar first: https://github.com/swiftbar/SwiftBar/releases (or install Homebrew)." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
step "Plugin folder"
CURRENT_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
if [ -n "$PLUGIN_DIR" ]; then
  PLUGIN_DIR="$(cd "$PLUGIN_DIR" 2>/dev/null && pwd || echo "$PLUGIN_DIR")"
  run "mkdir -p '$PLUGIN_DIR'"
  run "ln -sfn '$PLUGIN_SRC' '$PLUGIN_DIR/claude-bar-sessions.5m.py'"
  say "linked plugin into $PLUGIN_DIR"
  if [ -z "$CURRENT_DIR" ]; then
    run "defaults write com.ameba.SwiftBar PluginDirectory -string '$PLUGIN_DIR'"
    say "SwiftBar plugin folder set to $PLUGIN_DIR"
  elif [ "$CURRENT_DIR" != "$PLUGIN_DIR" ]; then
    say "note: SwiftBar currently reads $CURRENT_DIR; change it in SwiftBar > Preferences if needed"
  fi
elif [ -n "$CURRENT_DIR" ] && [ -d "$CURRENT_DIR" ] && [ "$CURRENT_DIR" != "$REPO/plugin" ]; then
  run "ln -sfn '$PLUGIN_SRC' '$CURRENT_DIR/claude-bar-sessions.5m.py'"
  say "linked plugin into SwiftBar's existing folder: $CURRENT_DIR"
else
  run "defaults write com.ameba.SwiftBar PluginDirectory -string '$REPO/plugin'"
  say "SwiftBar plugin folder set to $REPO/plugin"
fi
# ---------------------------------------------------------------------------
step "State folder"
STATE_DIR="$(python3 "$REPO/lib/cbs.py" state_dir)"
run "mkdir -p '$STATE_DIR'"
say "$STATE_DIR"
CONFIG_FILE="$(python3 "$REPO/lib/cbs.py" config_file)"
if [ -f "$CONFIG_FILE" ]; then
  say "config: $CONFIG_FILE"
else
  say "no config file (defaults apply). Optional: copy config.example.json to $CONFIG_FILE"
fi

# ---------------------------------------------------------------------------
if [ "$WITH_HOOK" = 1 ]; then
  step "Session-naming hook"
  SETTINGS="$HOME/.claude/settings.json"
  HOOK_CMD="python3 $REPO/hooks/auto-name-session.py"
  if [ "$DRY" = 1 ]; then
    say "[dry-run] add UserPromptSubmit hook '$HOOK_CMD' to $SETTINGS"
  else
    python3 - "$SETTINGS" "$HOOK_CMD" <<'PY'
import json, os, sys
path, cmd = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
hooks = data.setdefault("hooks", {})
groups = hooks.setdefault("UserPromptSubmit", [])
present = any(h.get("command") == cmd for g in groups for h in g.get("hooks", []))
if present:
    print("  hook already present")
else:
    groups.append({"hooks": [{"type": "command", "command": cmd, "timeout": 15}]})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"  hook added to {path}")
PY
  fi
fi

# ---------------------------------------------------------------------------
if [ "$LOGIN_ITEM" = 1 ]; then
  step "Login item"
  if osascript -e 'tell application "System Events" to get name of every login item' 2>/dev/null | grep -q "SwiftBar"; then
    say "SwiftBar already in Login Items"
  else
    run "osascript -e 'tell application \"System Events\" to make login item at end with properties {path:\"$SWIFTBAR_APP\", hidden:false}' >/dev/null"
    say "added SwiftBar to Login Items"
  fi
fi

# ---------------------------------------------------------------------------
if [ "$LAUNCH" = 1 ]; then
  step "Launch SwiftBar"
  run "pkill -x SwiftBar 2>/dev/null || true"
  run "sleep 1"
  run "open -a SwiftBar"
  say "started"
fi

# ---------------------------------------------------------------------------
step "Done"
cat <<TXT
  Look for "CC" in the menu bar (the label is configurable).
  First click on "Resume session" triggers a macOS prompt to let SwiftBar
  control Terminal. Allow it once.
  Naming hook: $([ "$WITH_HOOK" = 1 ] && echo "wired" || echo "not wired (re-run with --hook)")
TXT
