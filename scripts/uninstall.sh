#!/bin/bash
# Uninstall claude-continue from iTerm2 AutoLaunch

set -e

ITERM_SCRIPTS_DIR="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch"
LINK_PATH="$ITERM_SCRIPTS_DIR/claude-continue"

echo "=== Claude Continue Uninstaller ==="
echo ""

if [[ -L "$LINK_PATH" ]] || [[ -d "$LINK_PATH" ]]; then
    echo "Removing $LINK_PATH..."
    rm -rf "$LINK_PATH"
    echo "Done. Claude Continue has been uninstalled."
    echo "Restart iTerm2 to complete the uninstallation."
else
    echo "Claude Continue is not installed (no symlink found at $LINK_PATH)"
fi
