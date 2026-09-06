#!/usr/bin/env python3
"""Generate short titles for Claude Code sessions that have none.

Reads the plugin cache, finds sessions without a title, and asks Claude
(`claude -p`, model from config, default haiku) for a 3-8 word label. The
result is stored in the cache as `aiSummary` and shown by the menu.

Sessions that already carry a customTitle (from /rename or the naming hook)
are skipped. Run the plugin once before this script so the cache exists.

Usage:
    generate-session-summaries.py             # backfill everything missing
    generate-session-summaries.py --limit 5   # at most 5
    generate-session-summaries.py --dry-run   # list what would be generated
    generate-session-summaries.py --regen     # clear all AI titles and redo
"""
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import cbs  # noqa: E402

SYSTEM_PROMPT = (
    "You are a labeling machine. You ONLY output short titles. You never answer questions, "
    "give advice, or use markdown. Output ONLY the title, nothing else."
)

PROMPT_TEMPLATE = """Label this session in 3-8 words. Session date: {session_date}

Rules: concise title, not a sentence. Lead with the project or client name if identifiable. Add the date as M/D when relevant. No markdown, no bold, no quotes, no periods.

Good: Pricing model overhaul, CRM contact enrichment fields, Stakeholder update 3/18, Knowledge base manifest cleanup

SESSION PROMPT TO LABEL: {first_prompt}

TITLE:"""

# The model sometimes answers the prompt instead of labeling it. Reject those.
REJECT_PATTERNS = [
    r"(?i)^I need", r"(?i)^Yes", r"(?i)^Found", r"(?i)^Sure", r"(?i)^Here",
    r"(?i)^Let me", r"(?i)^The ", r"(?i)user asked", r"(?i)session opened",
    r"(?i)no work yet", r"(?i)haven't executed", r"(?i)no substantive",
    r"(?i)not yet", r"(?i)can't summarize", r"(?i)skill invoked",
    r"(?i)your .* is", r"(?i)documented as",
]


def load_cache():
    cache = cbs.read_json(cbs.cache_file(), None)
    if not isinstance(cache, dict):
        print(f"Cache not found at {cbs.cache_file()}. Run the plugin once to build it.")
        sys.exit(1)
    return cache


def save_cache(cache):
    cbs.write_json_atomic(cbs.cache_file(), cache, compact=True)


def needs_summary(session):
    if session.get("aiSummary") or session.get("customTitle") or session.get("aiTitle"):
        return False
    if not session.get("firstPrompt") or session.get("isSidechain"):
        return False
    if session.get("messageCount", 0) < 2:
        return False
    return cbs.project_included(session.get("cwd") or "")


def format_session_date(session):
    created = session.get("created")
    if created:
        try:
            return datetime.fromisoformat(created.replace("Z", "+00:00")).strftime("%B %-d, %Y")
        except (ValueError, AttributeError):
            pass
    modified = session.get("modified", 0)
    if isinstance(modified, (int, float)) and modified > 0:
        return datetime.fromtimestamp(modified, tz=timezone.utc).strftime("%B %-d, %Y")
    return "unknown date"


def generate_summary(first_prompt, session_date):
    if len(first_prompt) > 500:
        first_prompt = first_prompt[:500] + "..."
    prompt = PROMPT_TEMPLATE.format(first_prompt=first_prompt, session_date=session_date)
    try:
        result = subprocess.run(
            [
                cbs.find_claude(), "-p",
                "--model", cbs.load_config()["title_model"],
                "--tools", "",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--no-session-persistence",
                "--system-prompt", SYSTEM_PROMPT,
                prompt,
            ],
            capture_output=True, text=True, timeout=30, cwd="/tmp",
            # Standalone run: no CLAUDE* vars from a parent session, and the
            # naming hook inside the inner claude -p stays quiet.
            env={**{k: v for k, v in os.environ.items() if not k.startswith("CLAUDE")},
                 "AUTONAME_IN_PROGRESS": "1"},
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None

    summary = re.sub(r"\*+", "", result.stdout.strip()).strip('"\'').strip()
    if "\n" in summary:
        summary = summary.split("\n")[0].strip()
    summary = summary.rstrip(".")
    words = summary.split()
    if len(words) > 10:
        summary = " ".join(words[:10])
    if any(re.search(p, summary) for p in REJECT_PATTERNS):
        return None
    return summary or None


def main():
    dry_run = "--dry-run" in sys.argv
    regen = "--regen" in sys.argv
    limit = None
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            limit = int(sys.argv[i + 1])

    cache = load_cache()
    sessions = cache.get("sessions", {})

    if regen:
        cleared = 0
        for s in sessions.values():
            if s.get("aiSummary"):
                s["aiSummary"] = None
                cleared += 1
        print(f"Cleared {cleared} existing summaries")
        save_cache(cache)

    pending = [(sid, s) for sid, s in sessions.items() if needs_summary(s)]
    pending.sort(key=lambda x: x[1].get("modified", 0), reverse=True)
    if limit:
        pending = pending[:limit]
    print(f"Sessions needing summaries: {len(pending)}")

    if dry_run:
        for sid, s in pending[:20]:
            print(f"  {sid[:8]}  {s.get('firstPrompt', '')[:80]}")
        if len(pending) > 20:
            print(f"  ... and {len(pending) - 20} more")
        return

    generated = failed = 0
    for i, (sid, s) in enumerate(pending):
        print(f"[{i + 1}/{len(pending)}] {sid[:8]}... ", end="", flush=True)
        summary = generate_summary(s.get("firstPrompt", ""), format_session_date(s))
        if summary:
            sessions[sid]["aiSummary"] = summary
            generated += 1
            print(f"-> {summary}")
        else:
            failed += 1
            print("REJECTED/FAILED")
        if generated and generated % 10 == 0:
            save_cache(cache)
            print(f"  (saved {generated} so far)")
        time.sleep(0.2)

    if generated:
        save_cache(cache)
    print(f"\nDone: {generated} generated, {failed} rejected/failed")


if __name__ == "__main__":
    main()
