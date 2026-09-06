#!/usr/bin/env python3
"""UserPromptSubmit hook: name unnamed Claude Code sessions, without blocking.

Reads JSON from stdin (session_id, transcript_path, prompt). On the first real
prompt of an unnamed session it spawns a detached worker that asks Claude for a
Title Case name, then exits at once with {}. On the next prompt it picks the
result up from a file in /tmp and returns hookSpecificOutput.sessionTitle so
Claude Code applies it. The title lands in the transcript, so both `/resume`
and the menu bar plugin see it.

State files per session_id, in /tmp:
  claude-name-<sid>.lock   generation in progress (file age = mtime)
  claude-name-<sid>.txt    result ready, apply on next prompt

Rule: never block and never fail loudly. On any error emit {} and exit 0.

Wire it in ~/.claude/settings.json (install.sh --hook does this):
  "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command",
     "command": "python3 /path/to/claude-bar-sessions/hooks/auto-name-session.py", "timeout": 15}]}]}
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lib"))
sys.path.insert(0, str(HERE))
import cbs  # noqa: E402
import auto_name_registry as registry  # noqa: E402

WORKER_PATH = HERE / "auto-name-worker.py"
TMP_DIR = Path("/tmp")
LOCK_STALE_SECONDS = 180
MIN_PROMPT_LEN = 40  # shorter prompts are usually acks or follow-ups, not a topic


def log(action, session_id, name="", note=""):
    try:
        cbs.ensure_state_dir()
        with cbs.log_file().open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{action}\t{session_id}\t{name}\t{note}\n")
    except Exception:
        pass


def emit(obj):
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def read_current_title(session_id, transcript_path):
    """The session's current title, or "" if none.

    The transcript JSONL is authoritative: both /rename and this hook append a
    {"type":"custom-title"} entry and the last one in file order is current.
    sessions-index.json is only a fallback for older Claude Code versions.
    """
    if not transcript_path:
        return ""
    try:
        tp = Path(transcript_path)
        if tp.exists():
            latest = ""
            for line in tp.read_text(errors="ignore").splitlines():
                if '"custom-title"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "custom-title":
                    t = (obj.get("customTitle") or "").strip()
                    if t:
                        latest = t
            if latest:
                return latest
    except Exception:
        pass
    try:
        data = cbs.read_json(Path(transcript_path).parent / "sessions-index.json", {})
        for entry in data.get("entries", []):
            if entry.get("sessionId") == session_id:
                return (entry.get("customTitle") or "").strip()
    except Exception:
        pass
    return ""


def sanitize_name(raw):
    if not raw or not raw.strip():
        return ""
    name = raw.strip().splitlines()[0].strip()
    while name and name[0] in ('"', "'", "`", "*"):
        name = name[1:].strip()
    while name and name[-1] in ('"', "'", "`", "*"):
        name = name[:-1].strip()
    name = re.sub(r"[.!?,;:]+$", "", name).strip()
    if not name or len(name) > 80:
        return ""
    if name.startswith("#") or name.lower().startswith(("here", "title:", "name:")):
        return ""
    return name


def spawn_worker(session_id, prompt):
    """Start the worker detached and return at once."""
    lock_path = TMP_DIR / f"claude-name-{session_id}.lock"
    result_path = TMP_DIR / f"claude-name-{session_id}.txt"
    try:
        lock_path.write_text(str(os.getpid()))
        env = os.environ.copy()
        env["AUTONAME_SESSION_ID"] = session_id
        env["AUTONAME_PROMPT"] = prompt[:4000]
        env["AUTONAME_RESULT_PATH"] = str(result_path)
        env["AUTONAME_LOCK_PATH"] = str(lock_path)
        env["AUTONAME_IN_PROGRESS"] = "1"  # stops the inner `claude -p` from recursing into this hook
        subprocess.Popen(
            [sys.executable or "python3", str(WORKER_PATH)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True, env=env, cwd="/tmp",
        )
    except Exception as e:
        log("error", session_id, note=f"spawn-failed: {str(e)[:120]}")
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def main():
    try:
        # The worker's `claude -p` call fires UserPromptSubmit hooks of its own.
        # Without this guard every naming call would spawn another worker.
        if os.environ.get("AUTONAME_IN_PROGRESS"):
            emit({})
            return

        raw = sys.stdin.read()
        if not raw.strip():
            emit({})
            return
        data = json.loads(raw)
        session_id = data.get("session_id", "")
        transcript_path = data.get("transcript_path", "")
        prompt = (data.get("prompt") or "").strip()
        if not session_id:
            emit({})
            return

        current_title = read_current_title(session_id, transcript_path)
        eligible, reason = registry.is_eligible(session_id, current_title)
        if not eligible:
            if reason in ("locked", "manual-pre-existing", "manual-divergence"):
                try:
                    (TMP_DIR / f"claude-name-{session_id}.txt").unlink(missing_ok=True)
                    (TMP_DIR / f"claude-name-{session_id}.lock").unlink(missing_ok=True)
                except Exception:
                    pass
                if reason != "locked":
                    log("locked-by-user", session_id, name=current_title, note=reason)
            emit({})
            return

        # Name once, then leave the session alone.
        if reason == "we-own-it":
            emit({})
            return

        result_path = TMP_DIR / f"claude-name-{session_id}.txt"
        lock_path = TMP_DIR / f"claude-name-{session_id}.lock"

        if result_path.exists():
            try:
                name = sanitize_name(result_path.read_text())
                result_path.unlink(missing_ok=True)
                lock_path.unlink(missing_ok=True)
                if name:
                    registry.record_set(session_id, name)
                    log("applied", session_id, name=name)
                    emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "sessionTitle": name}})
                    return
            except Exception:
                pass

        if lock_path.exists():
            try:
                if time.time() - lock_path.stat().st_mtime < LOCK_STALE_SECONDS:
                    emit({})
                    return
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass

        if len(prompt) < MIN_PROMPT_LEN:
            emit({})
            return

        log("spawn", session_id)
        spawn_worker(session_id, prompt)
        emit({})
    except Exception as e:
        log("error", "?", note=str(e)[:200])
        emit({})


if __name__ == "__main__":
    main()
