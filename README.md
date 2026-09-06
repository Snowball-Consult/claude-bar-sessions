# claude-bar-sessions

A macOS menu bar list of your Claude Code sessions, with one click to resume any of them.

Built on [SwiftBar](https://swiftbar.app). Shows a `CC` item in the menu bar. The dropdown lists sessions grouped by **Ongoing**, **Active**, **Today**, **Yesterday**, **This week**, and **Older**, each with the best title available. Clicking a session opens a new Terminal window in that session's working directory and runs `claude --resume <id>`.

Included:

- **The plugin** (`plugin/claude-bar-sessions.5m.py`). Reads Claude Code's own session files. Refreshes every 5 minutes. Works across every project folder Claude Code has seen.
- **Pins.** Mark a session as "ongoing" from its submenu. Pinned sessions stay at the top, and "Restore ongoing (N)" reopens all of them at once after a reboot or logout.
- **A session-naming hook** (`hooks/`). Optional. Names every new session after its first prompt, in the background, so the list reads like a list of topics rather than a list of truncated first sentences. The name goes into the transcript, so `claude --resume` shows it too.
- **A batch titler** (`bin/generate-session-summaries.py`). Optional. Backfills titles for older sessions.

Zero dependencies beyond macOS, Python 3 (ships with Xcode Command Line Tools), SwiftBar, and the `claude` CLI.

## Install

```bash
git clone https://github.com/Snowball-Consult/claude-bar-sessions.git ~/claude-bar-sessions
cd ~/claude-bar-sessions
./install.sh
```

`install.sh` installs SwiftBar through Homebrew if it is missing, points SwiftBar at `plugin/` (or links the plugin into the folder SwiftBar already uses), adds SwiftBar to Login Items, and starts it. Run it again any time; each step checks its own state first.

Options:

| Flag | Effect |
|------|--------|
| `--hook` | Wire the session-naming hook into `~/.claude/settings.json` |
| `--plugin-dir DIR` | Link the plugin into `DIR` instead of using `plugin/` (for people who already keep SwiftBar plugins in one folder) |
| `--no-login-item` | Skip the Login Items step |
| `--no-launch` | Do not restart SwiftBar at the end |
| `--dry-run` | Print every action without doing it |

The first time you click **Resume session**, macOS asks whether SwiftBar may control Terminal. Allow it once.

To remove everything: `./uninstall.sh`. It leaves SwiftBar and the state folder in place and prints the path.

## How titles are chosen

For each session, the first available of:

1. **Custom title** from `/rename` or from the naming hook (stored in the transcript as a `custom-title` entry).
2. **Claude Code's own title** (the `ai-title` entry that Claude Code 2.1 and later writes into the transcript).
3. **Batch title** from `generate-session-summaries.py` (stored in the plugin cache).
4. **Summary** from `sessions-index.json`, which older Claude Code versions maintained.
5. **First prompt**, cleaned and cut to about ten words.

## The naming hook

`hooks/auto-name-session.py` runs on `UserPromptSubmit`. On the first prompt of an unnamed session it starts a detached worker that asks Claude (Haiku by default) for a 4-9 word Title Case name and returns immediately, so the prompt is never delayed. The naming call runs with no tools and no MCP servers, so it stays small however many connectors your account has. On the next prompt it applies the name. A session you rename yourself is locked and never touched again. State lives in `~/.local/state/claude-bar-sessions/`.

Wire it with `./install.sh --hook`, or add this to `~/.claude/settings.json` by hand:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /Users/you/claude-bar-sessions/hooks/auto-name-session.py",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

To use your own naming instructions, put them in a text file and set `naming_prompt_file` in the config. The user's first prompt is appended to your text.

## Configuration

Optional. Create `~/.config/claude-bar-sessions/config.json` (start from `config.example.json`). Every key has a default.

| Key | Default | Meaning |
|-----|---------|---------|
| `claude_home` | `~/.claude` | Where Claude Code keeps `projects/` and `sessions/` |
| `projects` | `[]` | Only list sessions whose working directory is under one of these paths. Empty means all projects. |
| `exclude_projects` | `["/tmp", "/private/tmp"]` | Hide sessions whose working directory is under one of these paths |
| `claude_bin` | auto | Path to the `claude` binary. Auto tries `PATH`, then `~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`. |
| `title_model` | `haiku` | Model for the naming hook and the batch titler |
| `naming_prompt_file` | none | Text file with your own naming instructions for the hook |
| `menu_label` | `CC` | Text shown in the menu bar |
| `appearance` | `auto` | `auto` follows the system theme (via SwiftBar's `OS_APPEARANCE`, then the `AppleInterfaceStyle` default). `light` or `dark` forces a palette. |
| `max_today`, `max_yesterday`, `max_this_week`, `max_older` | 20, 10, 8, 10 | Rows per group before "+N more" |

When sessions from more than one project are listed, each row shows the project folder name in brackets.

## Files and state

| Path | Purpose |
|------|---------|
| `plugin/claude-bar-sessions.5m.py` | The SwiftBar plugin. The only file SwiftBar runs. |
| `bin/resume-session.sh` | Opens Terminal in the session's directory and runs `claude --resume` |
| `bin/pin-session.sh`, `bin/pin-current.sh` | Pin or unpin a session by ID, or the session you are currently inside |
| `bin/restore-ongoing.sh` | Reopens every pinned session that is not running |
| `bin/generate-session-summaries.py` | Batch titler for older sessions |
| `hooks/` | The naming hook and its worker and registry |
| `lib/cbs.py` | Shared paths, config, and `claude` lookup |
| `~/.local/state/claude-bar-sessions/` | Cache, pins, naming registry, hook log (override with `CBS_STATE_DIR`) |
| `~/.config/claude-bar-sessions/config.json` | Optional config (override the folder with `CBS_CONFIG_DIR`) |

Helper scripts live outside `plugin/` on purpose: SwiftBar runs every executable in its plugin folder, including subfolders.

## How it reads sessions

Claude Code writes one JSONL transcript per session under `~/.claude/projects/<project>/`. The plugin reads the first real user prompt, the working directory, the latest `custom-title` entry, and the message count from each file, and caches the result keyed by file modification time. Warm refreshes touch only changed files. Live sessions are detected through `~/.claude/sessions/<pid>.json`.

Sessions with fewer than two user messages, sidechains, and sessions started by the hook's own `claude -p` calls are hidden.

## Troubleshooting

- **SwiftBar starts but shows nothing, and never writes its preferences.** Gatekeeper is holding the quarantined app. Run `xattr -dr com.apple.quarantine /Applications/SwiftBar.app` in a terminal, then start it again. `install.sh` installs with `--no-quarantine` to avoid this.
- **Junk items appear in the menu bar** (question marks, script output). SwiftBar is running helper scripts as plugins. Point it at `plugin/` only, or disable the extra files in SwiftBar > Preferences > Plugins.
- **Resume opens Terminal but the session picker shows nothing.** `claude --resume` scopes sessions to the working directory. The plugin resolves the directory from its cache; open the menu once (which refreshes the cache) and try again.
- **Titles never appear.** Check `~/.local/state/claude-bar-sessions/auto-name.log`. `claude-rc-*` lines mean the `claude` binary was found but failed (login state, model name). `missing-env` or no lines at all means the hook is not wired.
- **Colors do not match the theme.** The plugin picks a light or dark palette from SwiftBar's `OS_APPEARANCE` variable, which follows live switches including the Auto schedule. A switch shows up at the next refresh (5 minutes, or click Refresh). If SwiftBar reports the wrong theme on your build, set `appearance` to `light` or `dark` in the config. Primary text is never colored, so it always matches the menu.

## License

MIT. Copyright (c) 2026 Snowball Consult, LLC.
