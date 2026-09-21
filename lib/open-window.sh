#!/bin/bash
# Open a command in a new terminal window, using whichever terminal app the
# user configured. Sourced by the bin/ launchers so they behave identically.
#
# config.json:
#   "terminal": "Terminal"   macOS Terminal.app (default, historical behaviour)
#   "terminal": "Ghostty"    https://ghostty.org
#
# Anything else falls through to Terminal.app, so a typo degrades to the
# default rather than silently opening nothing.
#
# Both branches pass values as argv rather than interpolating them into the
# AppleScript source, so working directories containing spaces, quotes or
# backslashes need no escaping and cannot break the script.

cbs_open_window() {
    local cwd="$1" cmd="$2" term="$3" activate="${4:-yes}"

    if [ "$term" = "Ghostty" ]; then
        # Ghostty has no "do script". Its dictionary takes a surface
        # configuration instead: "initial working directory" sets the cwd and
        # "initial input" is typed into the shell that starts there. Together
        # those match what Terminal.app's "do script" does, and the shell stays
        # interactive after the command exits. "& return" presses Return.
        osascript - "$cwd" "$cmd" "$activate" <<'AS' >/dev/null
on run argv
  set theCwd to item 1 of argv
  set theCmd to item 2 of argv
  tell application "Ghostty"
    new window with configuration {initial working directory:theCwd, initial input:theCmd & return}
    if (item 3 of argv) is "yes" then activate
  end tell
end run
AS
    else
        # Terminal.app opens in the home directory, so the cd is part of the
        # command string here, unlike the Ghostty branch.
        osascript - "cd '$cwd' && $cmd" "$activate" <<'AS' >/dev/null
on run argv
  tell application "Terminal"
    do script (item 1 of argv)
    if (item 2 of argv) is "yes" then activate
  end tell
end run
AS
    fi
}
