#!/usr/bin/env python3
"""Background worker for auto-name-session.py.

Reads the session id and first prompt from the environment, asks Claude for a
Title Case session name, writes it to AUTONAME_RESULT_PATH, and removes
AUTONAME_LOCK_PATH on exit. Runs detached, so its runtime never blocks the user.

The naming instructions can be replaced with your own text file via the
`naming_prompt_file` config key. The user's first prompt is appended to it.
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import cbs  # noqa: E402

TIMEOUT_SECONDS = 60

DEFAULT_NAMING_INSTRUCTIONS = """You name Claude Code sessions so their owner can find them again weeks later in a session picker. The name is the only signal they see, so it must capture WHAT THE SESSION IS ABOUT, rather than what the first prompt happened to mention.

Read the user's first prompt and infer the OVERARCHING TOPIC or GOAL. Step back from surface details. The first prompt usually opens with one specific entry point or example. Ignore that detail and identify the broader thing the user is trying to do.

Too narrow (do NOT do this):
- "Read JSONL First Line"  (that is step 1, not the goal)
- "Inspect Sessions Index File"  (a tactic, not the topic)
- "Auto Name Generation"  (too generic, does not say what for)

Good (captures the overall thing):
- "Auto-Naming Claude Code Sessions"
- "Transcript Pipeline Refactor"
- "Fund Lookup Agent Design"
- "Session Hooks & Recursion Safety"

Format rules:
- Title Case
- 4-9 words
- No quotes, no period, no markdown, no preamble
- Lead with a project or client name if one appears
- Use an ampersand "&" to link two facets if useful

Output: the name only, on a single line. Nothing else.

USER'S FIRST PROMPT:
"""


def log(action, session_id, name="", note=""):
    try:
        cbs.ensure_state_dir()
        with cbs.log_file().open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{action}\t{session_id}\t{name}\t{note}\n")
    except Exception:
        pass


def naming_instructions():
    path = cbs.load_config().get("naming_prompt_file") or ""
    if path:
        try:
            text = Path(os.path.expanduser(path)).read_text()
            if text.strip():
                return text if text.endswith("\n") else text + "\n"
        except OSError:
            pass
    return DEFAULT_NAMING_INSTRUCTIONS


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


def main():
    session_id = os.environ.get("AUTONAME_SESSION_ID", "?")
    prompt = os.environ.get("AUTONAME_PROMPT", "")
    result_path = os.environ.get("AUTONAME_RESULT_PATH", "")
    lock_path = os.environ.get("AUTONAME_LOCK_PATH", "")

    name, note = "", ""
    try:
        if not prompt or not result_path:
            note = "missing-env"
        else:
            try:
                proc = subprocess.run(
                    [
                        cbs.find_claude(), "-p",
                        "--model", cbs.load_config()["title_model"],
                        "--tools", "",
                        "--no-session-persistence",
                        "--disable-slash-commands",
                        naming_instructions() + prompt,
                    ],
                    capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                    stdin=subprocess.DEVNULL, cwd="/tmp",
                )
                if proc.returncode == 0:
                    name = sanitize_name(proc.stdout)
                    if not name:
                        note = f"sanitize-rejected: {proc.stdout[:80]!r}"
                else:
                    note = f"claude-rc-{proc.returncode}: {proc.stderr[:120]}"
            except subprocess.TimeoutExpired:
                note = f"timeout-{TIMEOUT_SECONDS}s"
            except Exception as e:
                note = f"subprocess-error: {str(e)[:120]}"

        if name and result_path:
            try:
                Path(result_path).write_text(name)
                log("generated", session_id, name=name)
            except Exception as e:
                log("error", session_id, note=f"write-failed: {str(e)[:120]}")
        else:
            log("worker-no-name", session_id, note=note)
    finally:
        if lock_path:
            try:
                Path(lock_path).unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    main()
