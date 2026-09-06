#!/usr/bin/env python3
"""Shared helpers for claude-bar-sessions.

The plugin, the helper scripts in bin/, and the hooks in hooks/ all resolve
paths, the config, and the claude binary through this module, so one place
decides where things live.

Locations (each can be overridden with an environment variable):
  config  ~/.config/claude-bar-sessions/config.json   CBS_CONFIG_DIR
  state   ~/.local/state/claude-bar-sessions/         CBS_STATE_DIR

Command line use (for the shell scripts in bin/):
  python3 lib/cbs.py state_dir | cache_file | pins_file | claude_bin | claude_home
  python3 lib/cbs.py session_cwd <session-id>
  python3 lib/cbs.py last_cwd
  python3 lib/cbs.py current_session_id [<pid>]
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("CBS_CONFIG_DIR") or Path.home() / ".config" / "claude-bar-sessions")
STATE_DIR = Path(os.environ.get("CBS_STATE_DIR") or Path.home() / ".local" / "state" / "claude-bar-sessions")
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "claude_home": "~/.claude",
    "projects": [],
    "exclude_projects": ["/tmp", "/private/tmp"],
    "claude_bin": "",
    "title_model": "haiku",
    "naming_prompt_file": "",
    "menu_label": "CC",
    "max_today": 20,
    "max_yesterday": 10,
    "max_this_week": 8,
    "max_older": 10,
}

CLAUDE_CANDIDATES = [
    "~/.local/bin/claude",
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
]

_config_cache = None


def load_config():
    """Merge the user's config.json over the defaults. Unknown keys are ignored."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_FILE.exists():
            with CONFIG_FILE.open() as f:
                user = json.load(f)
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    _config_cache = cfg
    return cfg


def claude_home():
    return Path(os.path.expanduser(load_config()["claude_home"]))


def projects_dir():
    return claude_home() / "projects"


def sessions_dir():
    return claude_home() / "sessions"


def cache_file():
    return STATE_DIR / "sessions-cache.json"


def pins_file():
    return STATE_DIR / "session-pins.json"


def registry_file():
    return STATE_DIR / "auto-named-sessions.json"


def log_file():
    return STATE_DIR / "auto-name.log"


def ensure_state_dir():
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json_atomic(path, data, compact=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as f:
        if compact:
            json.dump(data, f, separators=(",", ":"))
        else:
            json.dump(data, f, indent=2)
    os.replace(tmp, path)


def find_claude():
    """Locate the claude binary. SwiftBar and hooks run with a minimal PATH,
    so PATH lookup alone is unreliable."""
    explicit = load_config().get("claude_bin") or ""
    if explicit:
        p = os.path.expanduser(explicit)
        if os.access(p, os.X_OK):
            return p
    found = shutil.which("claude")
    if found:
        return found
    for candidate in CLAUDE_CANDIDATES:
        p = os.path.expanduser(candidate)
        if os.access(p, os.X_OK):
            return p
    return "claude"


def _normpath(p):
    return os.path.normpath(os.path.expanduser(p))


def _under(path, prefix):
    return path == prefix or path.startswith(prefix + os.sep)


def project_included(cwd):
    """Apply the `projects` allowlist and `exclude_projects` prefixes to a session cwd."""
    if not cwd:
        return False
    cfg = load_config()
    norm = _normpath(cwd)
    for prefix in cfg.get("exclude_projects") or []:
        if _under(norm, _normpath(prefix)):
            return False
    allow = cfg.get("projects") or []
    if not allow:
        return True
    return any(_under(norm, _normpath(a)) for a in allow)


def cwd_from_project_dirname(name):
    """Fallback only: Claude Code names project folders by replacing '/' with '-'
    in the working directory. The mapping is lossy for paths that contain '-'."""
    if not name.startswith("-"):
        return ""
    return "/" + name[1:].replace("-", "/")


def session_cwd(session_id):
    """Working directory of a session, from the plugin's cache."""
    cache = read_json(cache_file(), {})
    entry = (cache.get("sessions") or {}).get(session_id) or {}
    return entry.get("cwd") or ""


def last_cwd():
    """Working directory of the most recently modified session in the cache."""
    cache = read_json(cache_file(), {})
    best, best_mtime = "", -1
    for entry in (cache.get("sessions") or {}).values():
        m = entry.get("modified") or 0
        if isinstance(m, (int, float)) and m > best_mtime and entry.get("cwd"):
            best, best_mtime = entry["cwd"], m
    return best


def resolve_current_session(start_pid=None):
    """Walk up the process tree until a `~/.claude/sessions/<pid>.json` matches.
    Returns (session_id, cwd), or ("", "") when not inside a Claude Code session."""
    pid = start_pid or os.getppid()
    sdir = sessions_dir()
    for _ in range(10):
        if not pid or pid <= 1:
            break
        info = read_json(sdir / f"{pid}.json", {})
        sid = info.get("sessionId")
        if sid:
            return sid, info.get("cwd") or ""
        try:
            out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True)
            pid = int(out.stdout.strip() or 0)
        except (ValueError, OSError):
            break
    return "", ""


def main(argv):
    key = argv[1] if len(argv) > 1 else ""
    arg = argv[2] if len(argv) > 2 else ""
    if key == "state_dir":
        print(STATE_DIR)
    elif key == "config_file":
        print(CONFIG_FILE)
    elif key == "cache_file":
        print(cache_file())
    elif key == "pins_file":
        print(pins_file())
    elif key == "claude_bin":
        print(find_claude())
    elif key == "claude_home":
        print(claude_home())
    elif key == "session_cwd":
        print(session_cwd(arg))
    elif key == "last_cwd":
        print(last_cwd())
    elif key == "current_session_id":
        sid, _ = resolve_current_session(int(arg) if arg else None)
        print(sid)
    else:
        print(__doc__.strip())
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
