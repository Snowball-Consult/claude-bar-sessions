"""Sidecar registry of the session names the auto-namer has set.

Stored at <state dir>/auto-named-sessions.json:
  {
    "<session_id>": {
      "set_to": "Auto-Naming Claude Code Sessions",   # what we wrote (or "" if locked)
      "locked": false,                                # true once a manual rename diverges
      "updated": "2026-05-01T..."
    }
  }

Ownership rule (consumed by the hook):
  - empty customTitle, no entry         -> free to set
  - customTitle == set_to               -> we own it
  - customTitle != set_to, locked=false -> user renamed manually, lock it now
  - locked == true                      -> never touch this session again

The registry survives reboots; the per-session lock and result files in /tmp do not.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import cbs  # noqa: E402


def _load():
    data = cbs.read_json(cbs.registry_file(), {})
    return data if isinstance(data, dict) else {}


def _save(data):
    try:
        cbs.write_json_atomic(cbs.registry_file(), dict(sorted(data.items())))
    except OSError:
        pass


def get_entry(session_id):
    return _load().get(session_id)


def record_set(session_id, name):
    """Record that we just set this session's title to <name>."""
    data = _load()
    data[session_id] = {"set_to": name, "locked": False, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save(data)


def lock(session_id, observed_title):
    """Mark this session as user-owned. Its title is never touched again."""
    data = _load()
    data[session_id] = {"set_to": observed_title, "locked": True, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _save(data)


def is_eligible(session_id, current_title):
    """Decide whether the auto-namer may set this session's title.

    Returns (eligible, reason). Side effect: a detected manual rename locks the
    session and returns ineligible.
    """
    entry = get_entry(session_id)
    title = (current_title or "").strip()

    if entry and entry.get("locked"):
        return False, "locked"
    if not entry:
        if title:
            lock(session_id, title)
            return False, "manual-pre-existing"
        return True, "no-title-no-entry"

    set_to = (entry.get("set_to") or "").strip()
    if not title:
        return True, "title-cleared"
    if title == set_to:
        return True, "we-own-it"
    lock(session_id, title)
    return False, "manual-divergence"
