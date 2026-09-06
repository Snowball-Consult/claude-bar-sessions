#!/usr/bin/env python3
"""claude-bar-sessions: a SwiftBar plugin that lists Claude Code sessions.

Shows recent sessions grouped by date, with the best available title for each
one. Click a session to resume it in Terminal.app in its own working directory.
Pin sessions as "ongoing" to keep them at the top and restore them in bulk.

Filename convention: the ".5m" suffix tells SwiftBar to refresh every 5 minutes.

Menu colors: SwiftBar 2.1.1 resolves its theme from the "AppleInterfaceStyle"
default, which reads nil on recent macOS builds even in dark mode, so both
plugin-side theme detection and SwiftBar's own "light,dark" color pairs pick
the light variant on a dark menu. Rule used here: primary text gets no color
parameter (the system's adaptive label color always matches the menu), and
accents use single mid-tone hues that read on both light and dark backgrounds.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import cbs  # noqa: E402

CFG = cbs.load_config()
BIN_DIR = cbs.REPO_ROOT / "bin"
RESUME_SCRIPT = str(BIN_DIR / "resume-session.sh")
PIN_SCRIPT = str(BIN_DIR / "pin-session.sh")
RESTORE_ONGOING_SCRIPT = str(BIN_DIR / "restore-ongoing.sh")

MAX_TODAY = int(CFG["max_today"])
MAX_YESTERDAY = int(CFG["max_yesterday"])
MAX_THIS_WEEK = int(CFG["max_this_week"])
MAX_OLDER = int(CFG["max_older"])

ACCENT_BLUE = "#4D7AFF"
ACCENT_ORANGE = "#FF9000"
TEXT_MUTED = "#9ca3af"
SUCCESS = "#10b981"

CACHE_VERSION = 2


# --------------------------------------------------------------------------
# Cache and pins
# --------------------------------------------------------------------------

def load_cache():
    data = cbs.read_json(cbs.cache_file(), None)
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return {"version": CACHE_VERSION, "sessions": {}}
    return data


def save_cache(cache):
    try:
        cbs.write_json_atomic(cbs.cache_file(), cache, compact=True)
    except OSError:
        pass


def load_pins():
    """Session IDs the user marked as ongoing."""
    data = cbs.read_json(cbs.pins_file(), {})
    return set((data.get("ongoing") or {}).keys())


# --------------------------------------------------------------------------
# Session parsing
# --------------------------------------------------------------------------

def is_real_user_prompt(content):
    """True for a user message that is an actual prompt, not command noise."""
    if not content:
        return False
    if content.startswith("<local-command-caveat>") or content.startswith("<local-command-stdout>"):
        return False
    stripped = re.sub(r"<[^>]+>", "", content).strip()
    return stripped.lower() not in ("exit", "quit", "q", "")


def extract_prompt_text(content):
    """Meaningful text of a user message, with slash commands kept as /name."""
    if not content:
        return ""
    cmd_match = re.search(r"<command-name>/([^<]+)</command-name>", content)
    if cmd_match:
        return f"/{cmd_match.group(1)}"
    text = re.sub(r"<[^>]+>", " ", content)
    return re.sub(r"\s+", " ", text).strip()


def parse_jsonl_session(filepath):
    """Read one session transcript and return its metadata, or None if empty."""
    first_prompt = None
    custom_title = None
    created = None
    cwd = None
    user_count = 0
    is_sidechain = False

    try:
        with open(filepath, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if cwd is None and entry.get("cwd"):
                    cwd = entry["cwd"]

                entry_type = entry.get("type")
                if entry_type == "user":
                    msg = entry.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        texts = [b.get("text", "") for b in content if b.get("type") == "text"]
                        content = " ".join(texts)
                    if is_real_user_prompt(content):
                        user_count += 1
                        if first_prompt is None:
                            first_prompt = extract_prompt_text(content)
                            created = entry.get("timestamp")
                elif entry_type == "custom-title":
                    # The last custom-title entry in file order is the current one.
                    custom_title = entry.get("customTitle")

                if entry.get("isSidechain") and entry_type in ("user", "assistant"):
                    is_sidechain = True
    except OSError:
        return None

    if first_prompt is None and custom_title is None:
        return None

    return {
        "firstPrompt": first_prompt or "",
        "customTitle": custom_title,
        "created": created,
        "cwd": cwd or cbs.cwd_from_project_dirname(filepath.parent.name),
        "messageCount": user_count,
        "isSidechain": is_sidechain,
    }


def scan_jsonl_sessions(cache):
    """Scan every project folder. Files whose mtime is unchanged come from the cache."""
    sessions = cache.get("sessions", {})
    updated = False
    projects_dir = cbs.projects_dir()
    if not projects_dir.exists():
        return sessions, updated

    seen = set()
    for filepath in projects_dir.glob("*/*.jsonl"):
        session_id = filepath.stem
        seen.add(session_id)
        try:
            mtime = filepath.stat().st_mtime
        except OSError:
            continue

        cached = sessions.get(session_id)
        if cached and cached.get("modified") == mtime and cached.get("source") == "jsonl":
            continue

        parsed = parse_jsonl_session(filepath)
        if parsed is None:
            continue

        sessions[session_id] = {
            "firstPrompt": parsed["firstPrompt"],
            "customTitle": parsed["customTitle"],
            "aiSummary": cached.get("aiSummary") if cached else None,
            "summary": cached.get("summary") if cached else None,
            "created": parsed["created"],
            "modified": mtime,
            "cwd": parsed["cwd"],
            "messageCount": parsed["messageCount"],
            "isSidechain": parsed["isSidechain"],
            "source": "jsonl",
        }
        updated = True

    # Drop cache entries whose transcript file is gone.
    for session_id in [s for s, v in sessions.items() if v.get("source") == "jsonl" and s not in seen]:
        del sessions[session_id]
        updated = True

    return sessions, updated


def load_index_sessions(sessions):
    """Older Claude Code versions kept a sessions-index.json per project.
    Merge any entries that have no transcript file of their own."""
    updated = False
    projects_dir = cbs.projects_dir()
    if not projects_dir.exists():
        return sessions, updated

    for index_file in projects_dir.glob("*/sessions-index.json"):
        data = cbs.read_json(index_file, None)
        if not isinstance(data, dict):
            continue
        fallback_cwd = cbs.cwd_from_project_dirname(index_file.parent.name)
        for entry in data.get("entries", []):
            sid = entry.get("sessionId")
            if not sid:
                continue
            if sid in sessions:
                if sessions[sid].get("summary") is None and entry.get("summary"):
                    sessions[sid]["summary"] = entry["summary"]
                    updated = True
                continue
            file_mtime = entry.get("fileMtime")
            sessions[sid] = {
                "firstPrompt": entry.get("firstPrompt", ""),
                "customTitle": entry.get("customTitle"),
                "aiSummary": None,
                "summary": entry.get("summary"),
                "created": entry.get("created"),
                "modified": file_mtime / 1000 if isinstance(file_mtime, (int, float)) else 0,
                "cwd": entry.get("cwd") or fallback_cwd,
                "messageCount": entry.get("messageCount", 0),
                "isSidechain": entry.get("isSidechain", False),
                "source": "index",
            }
            updated = True

    return sessions, updated


def get_active_sessions():
    """Session IDs with a live Claude Code process."""
    active = set()
    sessions_dir = cbs.sessions_dir()
    if not sessions_dir.exists():
        return active
    for f in sessions_dir.glob("*.json"):
        info = cbs.read_json(f, {})
        pid = info.get("pid")
        sid = info.get("sessionId")
        if not (pid and sid):
            continue
        try:
            os.kill(pid, 0)
            active.add(sid)
        except (ProcessLookupError, PermissionError, TypeError, OverflowError):
            pass
    return active


# --------------------------------------------------------------------------
# Display names
# --------------------------------------------------------------------------

def clean_first_prompt(text):
    """Turn a first prompt into a display name of about ten words."""
    if not text:
        return None

    skill_match = re.match(r"^/(\S+)\s*(.*)", text)
    if skill_match:
        label = skill_match.group(1).replace("-", " ").replace("_", " ").title()
        rest = skill_match.group(2).strip()
        if rest:
            return f"{label}: {' '.join(rest.split()[:7])}"
        return label

    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(
        r"^(?:okay|hey|so|um|uh|alright|please|can you|could you|I need you to|I want you to)\s*[,:]?\s*",
        "", text, flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if len(words) > 10:
        text = " ".join(words[:10]) + "..."
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text or None


def get_display_name(session):
    """Title priority: /rename or hook title, batch AI summary, index summary, first prompt."""
    if session.get("customTitle"):
        return session["customTitle"]
    if session.get("aiSummary"):
        return session["aiSummary"]
    summary = session.get("summary")
    if summary and "API Error" not in summary and "error" not in summary.lower():
        return summary
    cleaned = clean_first_prompt(session.get("firstPrompt", ""))
    return cleaned or "Untitled session"


def filter_sessions(sessions):
    """Drop sidechains, one-message sessions, error sessions, and excluded projects."""
    filtered = {}
    for sid, s in sessions.items():
        if s.get("isSidechain"):
            continue
        if s.get("messageCount", 0) < 2:
            continue
        fp = s.get("firstPrompt", "") or ""
        summary = s.get("summary", "") or ""
        if "API Error" in fp or "API Error" in summary:
            continue
        if "Summarize this Claude Code session" in fp or "labeling machine" in fp:
            continue
        if not cbs.project_included(s.get("cwd") or ""):
            continue
        filtered[sid] = s
    return filtered


# --------------------------------------------------------------------------
# Grouping and formatting
# --------------------------------------------------------------------------

def get_modified_dt(session):
    mod = session.get("modified", 0)
    if isinstance(mod, (int, float)) and mod > 0:
        return datetime.fromtimestamp(mod, tz=timezone.utc)
    created = session.get("created")
    if created:
        try:
            return datetime.fromisoformat(created.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def group_sessions(sessions):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    week_start = today_start - timedelta(days=today_start.weekday())

    groups = {"ongoing": [], "active": [], "today": [], "yesterday": [], "this_week": [], "older": []}
    for sid, s in sessions.items():
        dt = get_modified_dt(s)
        entry = (sid, s, dt)
        if dt >= today_start:
            groups["today"].append(entry)
        elif dt >= yesterday_start:
            groups["yesterday"].append(entry)
        elif dt >= week_start:
            groups["this_week"].append(entry)
        else:
            groups["older"].append(entry)
    for key in groups:
        groups[key].sort(key=lambda x: x[2], reverse=True)
    return groups


def format_time(dt, group_key):
    local_dt = dt.astimezone()
    if group_key in ("today", "yesterday", "active", "ongoing"):
        return local_dt.strftime("%-I:%M %p")
    if group_key == "this_week":
        return local_dt.strftime("%a")
    return local_dt.strftime("%b %-d")


def time_ago(dt):
    minutes = int((datetime.now(timezone.utc) - dt).total_seconds() / 60)
    if minutes < 1:
        return "now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def resume_action(session_id):
    return f"bash={RESUME_SCRIPT} param1={session_id} terminal=false"


def render_session_line(sid, s, dt, group_key, ongoing_set, show_project, color=None):
    """One session row plus its submenu (Resume / Pin or Unpin).

    color=None leaves the color parameter out so the system's adaptive label
    color applies; pass a hue only to de-emphasize a row.
    """
    name = get_display_name(s)
    if len(name) > 45:
        name = name[:42] + "..."
    ts = time_ago(dt) if group_key == "active" else format_time(dt, group_key)
    is_pinned = sid in ongoing_set
    marker = " *" if (group_key == "active" and is_pinned) else ""
    project = ""
    if show_project and s.get("cwd"):
        project = f"  [{os.path.basename(s['cwd'].rstrip('/')) or s['cwd']}]"
    resume = resume_action(sid)
    color_part = f"color={color} " if color else ""
    print(f"{name}{marker}{project}  {ts} | {color_part}size=13 {resume}")
    print(f"--Resume session | {color_part}size=12 {resume}")
    pin_label = "Unpin from ongoing" if is_pinned else "Pin as ongoing"
    pin = f"bash={PIN_SCRIPT} param1={sid} param2=toggle terminal=false refresh=true"
    print(f"--{pin_label} | {color_part}size=12 {pin}")


def render_group(groups, key, label, color, limit, ongoing_sids, show_project, row_color=None):
    entries = groups[key]
    if not entries:
        return
    print(f"{label} ({len(entries)}) | color={color} size=11 font=HelveticaNeue-Bold")
    for sid, s, dt in entries[:limit]:
        render_session_line(sid, s, dt, key, ongoing_sids, show_project, row_color)
    remaining = len(entries) - limit
    if remaining > 0:
        print(f"  +{remaining} more | color={TEXT_MUTED} size=11")
    print("---")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    cbs.ensure_state_dir()
    cache = load_cache()

    sessions, jsonl_updated = scan_jsonl_sessions(cache)
    sessions, index_updated = load_index_sessions(sessions)
    if jsonl_updated or index_updated:
        cache["sessions"] = sessions
        save_cache(cache)

    active_sids = get_active_sessions()
    ongoing_sids = load_pins()

    sessions = filter_sessions(sessions)
    show_project = len({s.get("cwd") for s in sessions.values() if s.get("cwd")}) > 1
    groups = group_sessions(sessions)

    # Running sessions get their own group.
    for group_key in ("today", "yesterday", "this_week", "older"):
        for entry in list(groups[group_key]):
            if entry[0] in active_sids:
                groups["active"].append(entry)
                groups[group_key].remove(entry)

    # Pinned sessions that are not running move to ONGOING.
    for group_key in ("today", "yesterday", "this_week", "older"):
        for entry in list(groups[group_key]):
            if entry[0] in ongoing_sids:
                groups["ongoing"].append(entry)
                groups[group_key].remove(entry)

    groups["active"].sort(key=lambda x: x[2], reverse=True)
    groups["ongoing"].sort(key=lambda x: x[2], reverse=True)
    restorable_ongoing = [e for e in groups["ongoing"] if e[0] not in active_sids]

    print(f"{CFG['menu_label']} | size=13")
    print("---")

    if restorable_ongoing:
        print(
            f"Restore ongoing ({len(restorable_ongoing)}) | "
            f"color={ACCENT_ORANGE} size=13 font=HelveticaNeue-Bold "
            f"bash={RESTORE_ONGOING_SCRIPT} terminal=false refresh=true "
            f"sfimage=arrow.clockwise.circle.fill sfcolor={ACCENT_ORANGE}"
        )
        print("---")

    render_group(groups, "ongoing", "ONGOING", ACCENT_ORANGE, len(groups["ongoing"]), ongoing_sids, show_project)
    render_group(groups, "active", "ACTIVE", SUCCESS, len(groups["active"]), ongoing_sids, show_project)
    render_group(groups, "today", "TODAY", ACCENT_BLUE, MAX_TODAY, ongoing_sids, show_project)
    render_group(groups, "yesterday", "YESTERDAY", ACCENT_BLUE, MAX_YESTERDAY, ongoing_sids, show_project)
    render_group(groups, "this_week", "THIS WEEK", TEXT_MUTED, MAX_THIS_WEEK, ongoing_sids, show_project)
    render_group(groups, "older", "OLDER", TEXT_MUTED, MAX_OLDER, ongoing_sids, show_project, TEXT_MUTED)

    if not any(groups[k] for k in groups):
        print(f"No sessions found | color={TEXT_MUTED} size=13")
        print("---")

    print(f"Browse all sessions... | bash={RESUME_SCRIPT} terminal=false sfimage=magnifyingglass sfcolor={ACCENT_BLUE}")
    print(f"Refresh | refresh=true sfimage=arrow.clockwise sfcolor={ACCENT_BLUE}")


if __name__ == "__main__":
    main()
